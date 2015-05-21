# Copyright (C) 2015 GRNET S.A.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from agkyra.syncer.setup import SyncerSettings
from agkyra.syncer.localfs_client import LocalfsFileClient, LocalfsTargetHandle
from agkyra.syncer.pithos_client import PithosFileClient
from agkyra.syncer.syncer import FileSyncer
from agkyra.syncer import messaging, utils, common
import random
import os
import time
import shutil

from agkyra.config import AgkyraConfig, CONFIG_PATH
from kamaki.clients import ClientError

import logging
logger = logging.getLogger('agkyra')
handler = logging.StreamHandler()
formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

cnf = AgkyraConfig()
cloud_conf = cnf.get('cloud', 'test')
if cloud_conf is None:
    print "Define a 'test' cloud in %s" % CONFIG_PATH
    exit()

AUTHENTICATION_URL = cloud_conf['url']
TOKEN = cloud_conf['token']

ID = "AGKYRATEST" + str(random.random()).split('.')[1]

LOCAL_ROOT_PATH = "/tmp/" + ID


settings = SyncerSettings(
    auth_url=AUTHENTICATION_URL,
    auth_token=TOKEN,
    container=ID,
    local_root_path=LOCAL_ROOT_PATH,
    ignore_ssl=True)

master = PithosFileClient(settings)
slave = LocalfsFileClient(settings)
s = FileSyncer(settings, master, slave)

pithos = master.endpoint
pithos.create_container(ID)

# initial upload to pithos
f1 = "f1"
f1_content1 = "content1"
r1 = pithos.upload_from_string(
    f1, f1_content1)
etag1 = r1['etag']

# check pithos state
pithos_cands = master.get_pithos_candidates()
info1 = pithos_cands[f1]["info"]
assert etag1 == info1["pithos_etag"]

db = s.get_db()
state = db.get_state(master.SIGNATURE, f1)
assert state.serial == -1
assert state.info == {}


def assert_message(mtype):
    m = s.get_next_message(block=True)
    print m
    assert isinstance(m, mtype)
    return m

# probe pithos
s.probe_file(master.SIGNATURE, f1)
assert_message(messaging.UpdateMessage)

state = db.get_state(master.SIGNATURE, f1)
assert state.serial == 0
assert state.info == info1

deciding = s.list_deciding()
assert deciding == set([f1])

# get local state
state = db.get_state(slave.SIGNATURE, f1)
assert state.serial == -1
assert state.info == {}

# sync
s.decide_file_sync(f1)
assert_message(messaging.SyncMessage)

# check local synced file
assert_message(messaging.AckSyncMessage)
state = db.get_state(slave.SIGNATURE, f1)
assert state.serial == 0
info = state.info
assert info['localfs_size'] == len(f1_content1)

f1_path = os.path.join(LOCAL_ROOT_PATH, f1)


def hash_file(fil):
    with open(fil) as f:
        return utils.hash_string(f.read())

assert hash_file(f1_path) == utils.hash_string(f1_content1)


# update local file
f1_content2 = "content22222"
with open(f1_path, "w") as f:
    f.write(f1_content2)

# update upstream
f1_content3 = "content33"
r3 = pithos.upload_from_string(
    f1, f1_content3)
etag3 = r1['etag']

# cause a conflict
assert s.get_next_message() is None
# first try to upload ignoring upstream changes
s.probe_file(slave.SIGNATURE, f1)
s.decide_file_sync(f1)

m = assert_message(messaging.UpdateMessage)
assert m.archive == slave.SIGNATURE

assert_message(messaging.SyncMessage)
assert_message(messaging.CollisionMessage)
assert_message(messaging.SyncErrorMessage)

# this will fail because serial is marked as failed
s.decide_file_sync(f1)
time.sleep(2)
assert s.get_next_message() is None

# now probe upstream too and retry
s.probe_file(master.SIGNATURE, f1)
s.decide_file_sync(f1)

m = assert_message(messaging.UpdateMessage)
assert m.archive == master.SIGNATURE

assert_message(messaging.SyncMessage)
assert_message(messaging.ConflictStashMessage)
assert_message(messaging.AckSyncMessage)

assert s.get_next_message() is None

# notifiers instead of probing
s.start_notifiers()

# make local dir with files
d1 = "d1"
d1_path = os.path.join(LOCAL_ROOT_PATH, d1)
logger.info('making dir %s' % d1)
os.mkdir(d1_path)
f2 = "d1/f2"
f2_path = os.path.join(LOCAL_ROOT_PATH, f2)
f2_content = "f2"
logger.info('making file %s' % f2)
with open(f2_path, "w") as f:
    f.write(f2_content)

print 'Sleeping to wait for filesystem events...'
time.sleep(2)
s.decide_all_archives()

assert_message(messaging.UpdateMessage)
assert_message(messaging.UpdateMessage)
assert_message(messaging.SyncMessage)
assert_message(messaging.SyncMessage)
assert_message(messaging.AckSyncMessage)
assert_message(messaging.AckSyncMessage)

assert s.get_next_message() is None
s.stop_notifiers()

# Check sym links
ln1 = "f1.link"
ln1_path = os.path.join(LOCAL_ROOT_PATH, ln1)
os.symlink(f1_path, ln1_path)
s.probe_file(s.SLAVE, ln1)
state = db.get_state(slave.SIGNATURE, ln1)
assert state.serial == 0
assert state.info == {"localfs_type": "unhandled"}

assert_message(messaging.UpdateMessage)

s.decide_file_sync(ln1)

assert_message(messaging.SyncMessage)
assert_message(messaging.AckSyncMessage)

# Put file upstream to cause conflict
upstream_ln1_content = "regular"
r1 = pithos.upload_from_string(
    ln1, upstream_ln1_content)
s.probe_file(s.MASTER, ln1)
s.probe_file(s.SLAVE, ln1)

assert_message(messaging.UpdateMessage)

s.decide_file_sync(ln1)

assert_message(messaging.SyncMessage)
m = assert_message(messaging.ConflictStashMessage)
stashed_ln1 = m.stash_name

assert_message(messaging.AckSyncMessage)

assert s.get_next_message() is None

s.probe_file(s.SLAVE, stashed_ln1)
m = assert_message(messaging.UpdateMessage)
assert m.objname == stashed_ln1

state = db.get_state(slave.SIGNATURE, stashed_ln1)
assert state.serial == 0
assert state.info == {"localfs_type": "unhandled"}
assert s.get_next_message() is None

# nothing to be synced
s.decide_file_sync(f1)
time.sleep(2)
assert s.get_next_message() is None

# directories
r = pithos.object_put(f1, content_type='application/directory',
                      content_length=0)
ff1 = "f1/ff1"
ff1_content = "ff1 in dir "
r1 = pithos.upload_from_string(ff1, ff1_content)
s.probe_file(s.MASTER, f1)
s.probe_file(s.MASTER, ff1)

assert_message(messaging.UpdateMessage)
assert_message(messaging.UpdateMessage)

# fails because file in place of dir
s.decide_file_sync(ff1)

assert_message(messaging.SyncMessage)
assert_message(messaging.SyncErrorMessage)

fd1 = "f1/fd1"
r = pithos.object_put(fd1, content_type='application/directory',
                      content_length=0)
s.probe_file(s.MASTER, fd1)
assert_message(messaging.UpdateMessage)

# also fails because file in place of dir
s.decide_file_sync(fd1)

assert_message(messaging.SyncMessage)
assert_message(messaging.SyncErrorMessage)

# fail due to active heartbeat
s.probe_file(s.MASTER, ff1)
time.sleep(1)
assert s.get_next_message() is None

s.decide_file_sync(ff1)
time.sleep(1)
assert s.get_next_message() is None

print "SLEEPING 10"
time.sleep(10)

# this will fail with serial mismatch
s.probe_file(s.MASTER, ff1)
s.decide_file_sync(ff1)

assert_message(messaging.SyncMessage)
assert_message(messaging.SyncErrorMessage)

print "SLEEPING 11"
time.sleep(11)

# locally remove f1 to allow a dir to be created
os.unlink(f1_path)
s.decide_file_sync(ff1)

assert_message(messaging.SyncMessage)
assert_message(messaging.AckSyncMessage)

# also fix the dir
s.probe_file(s.SLAVE, f1)
assert_message(messaging.UpdateMessage)
s.decide_file_sync(f1)
assert_message(messaging.SyncMessage)
assert_message(messaging.AckSyncMessage)

# ln1 is a file; let a dir be upstream
r = pithos.object_put(
    ln1, content_type='application/directory',
    content_length=0)

s.probe_file(s.MASTER, ln1)
s.decide_file_sync(ln1)

assert_message(messaging.UpdateMessage)
assert_message(messaging.SyncMessage)
assert_message(messaging.AckSyncMessage)
assert os.path.isdir(ln1_path)

# locally remove dir and file
shutil.rmtree(d1_path)
s.probe_file(s.SLAVE, d1)
s.probe_file(s.SLAVE, f2)

assert_message(messaging.UpdateMessage)
assert_message(messaging.UpdateMessage)

s.decide_file_sync(d1)
s.decide_file_sync(f2)

assert_message(messaging.SyncMessage)
assert_message(messaging.SyncMessage)
assert_message(messaging.AckSyncMessage)
assert_message(messaging.AckSyncMessage)

try:
    pithos.get_object_info(d1)
    assert False
except Exception as e:
    assert isinstance(e, ClientError) and e.status == 404

# delete upstream
pithos.del_object(f1)
pithos.del_object(ff1)
s.probe_file(s.MASTER, f1)
s.probe_file(s.MASTER, ff1)
assert_message(messaging.UpdateMessage)
assert_message(messaging.UpdateMessage)

# will fail because local dir is non-empty
s.decide_file_sync(f1)

assert_message(messaging.SyncMessage)
assert_message(messaging.SyncErrorMessage)

# but this is ok
s.decide_file_sync(ff1)

assert_message(messaging.SyncMessage)
assert_message(messaging.AckSyncMessage)

print "SLEEPING 11"
time.sleep(11)
s.decide_file_sync(f1)

assert_message(messaging.SyncMessage)
assert_message(messaging.AckSyncMessage)

# this will be changed after probe
fchanged = "fchanged"
fchanged_path = os.path.join(LOCAL_ROOT_PATH, fchanged)
with open(fchanged_path, "w") as f:
    f.write("fchanged orig")

s.probe_file(s.SLAVE, fchanged)
assert_message(messaging.UpdateMessage)

state = db.get_state(s.SLAVE, fchanged)
fchanged_info = state.info

fchanged_new = "new content changed"
with open(fchanged_path, "w") as f:
    f.write(fchanged_new)

s.decide_file_sync(fchanged)
assert_message(messaging.SyncMessage)
assert_message(messaging.LiveInfoUpdateMessage)
assert_message(messaging.AckSyncMessage)

state = db.get_state(s.SLAVE, fchanged)
new_fchanged_info = state.info
assert fchanged_info != new_fchanged_info
print new_fchanged_info
assert new_fchanged_info["localfs_size"] == len(fchanged_new)

fupch = "fupch"
r1 = pithos.upload_from_string(
    fupch, "fupch")
fupch_etag = r1['etag']

s.probe_file(s.MASTER, fupch)
assert_message(messaging.UpdateMessage)
state = db.get_state(s.MASTER, fupch)
fupch_info = state.info
assert fupch_info["pithos_etag"] == fupch_etag

r1 = pithos.upload_from_string(
    fupch, "fupch new")
new_fupch_etag = r1['etag']

s.decide_file_sync(fupch)
assert_message(messaging.SyncMessage)
assert_message(messaging.LiveInfoUpdateMessage)
assert_message(messaging.AckSyncMessage)
state = db.get_state(s.MASTER, fupch)
new_fupch_info = state.info
assert new_fupch_info["pithos_etag"] == new_fupch_etag

#############################################################
### INTERNALS

fupch_path = os.path.join(LOCAL_ROOT_PATH, fupch)
assert os.path.isfile(fupch_path)
state = db.get_state(s.SLAVE, fupch)
handle = LocalfsTargetHandle(s.settings, state)
hidden_filename = utils.join_path(handle.cache_hide_name,
                                  utils.hash_string(handle.objname))
hidden_path = handle.get_path_in_cache(hidden_filename)
assert not os.path.isfile(hidden_path)

assert db.get_cachename(hidden_filename) is None
handle.move_file()
assert os.path.isfile(hidden_path)
assert db.get_cachename(hidden_filename) is not None
handle.move_file()
assert os.path.isfile(hidden_path)

shutil.move(hidden_path, fupch_path)
assert db.get_cachename(hidden_filename) is not None
handle.move_file()
assert os.path.isfile(hidden_path)

# open file to cause busy error
f = open(hidden_path, "r")
try:
    handle.hide_file()
    assert False
except Exception as e:
    assert isinstance(e, common.BusyError)
