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
from agkyra.syncer.localfs_client import LocalfsFileClient
from agkyra.syncer.pithos_client import PithosFileClient
from agkyra.syncer.syncer import FileSyncer
from agkyra.syncer import messaging, utils
import random
import os
import time

from agkyra.config import AgkyraConfig, CONFIG_PATH

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
    instance=ID,
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

# probe pithos
s.probe_file(master.SIGNATURE, f1)
m = s.get_next_message(block=True)
assert isinstance(m, messaging.UpdateMessage)

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
m = s.get_next_message(block=True)
assert isinstance(m, messaging.SyncMessage)

# check local synced file
m = s.get_next_message(block=True)
assert isinstance(m, messaging.AckSyncMessage)
state = db.get_state(slave.SIGNATURE, f1)
assert state.serial == 0
info = state.info
assert info['localfs_size'] == len(f1_content1)

f1_path = os.path.join(LOCAL_ROOT_PATH, f1)
assert utils.hash_file(f1_path) == utils.hash_string(f1_content1)


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
s.probe_file(master.SIGNATURE, f1)
s.probe_file(slave.SIGNATURE, f1)
s.decide_file_sync(f1)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.UpdateMessage)
assert m.archive == master.SIGNATURE

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.UpdateMessage)
assert m.archive == slave.SIGNATURE

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.SyncMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.ConflictStashMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.AckSyncMessage)

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

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.UpdateMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.UpdateMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.SyncMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.SyncMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.AckSyncMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.AckSyncMessage)

assert s.get_next_message() is None
s.stop_notifiers()

########################################

# Check sym links
ln1 = "f1.link"
ln1_path = os.path.join(LOCAL_ROOT_PATH, ln1)
os.symlink(f1_path, ln1_path)
s.probe_file(s.SLAVE, ln1)
state = db.get_state(slave.SIGNATURE, ln1)
assert state.serial == 0
assert state.info == {"localfs_type": "unhandled"}

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.UpdateMessage)

s.decide_file_sync(ln1)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.SyncMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.AckSyncMessage)

# Put file upstream to cause conflict
upstream_ln1_content = "regular"
r1 = pithos.upload_from_string(
    ln1, upstream_ln1_content)
s.probe_file(s.MASTER, ln1)
s.probe_file(s.SLAVE, ln1)
m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.UpdateMessage)

s.decide_file_sync(ln1)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.SyncMessage)

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.ConflictStashMessage)
stashed_ln1 = m.stash_name

m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.AckSyncMessage)

assert s.get_next_message() is None

s.probe_file(s.SLAVE, stashed_ln1)
m = s.get_next_message(block=True)
print m
assert isinstance(m, messaging.UpdateMessage)
assert m.objname == stashed_ln1

state = db.get_state(slave.SIGNATURE, stashed_ln1)
assert state.serial == 0
assert state.info == {"localfs_type": "unhandled"}

print "FINISHED"
