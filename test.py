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
import unittest

from agkyra.config import AgkyraConfig, CONFIG_PATH
from kamaki.clients import ClientError

import logging
logger = logging.getLogger('agkyra')
handler = logging.StreamHandler()
formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def hash_file(fil):
    with open(fil) as f:
        return utils.hash_string(f.read())


class AgkyraTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cnf = AgkyraConfig()
        cloud_conf = cnf.get('cloud', 'test')
        if cloud_conf is None:
            print "Define a 'test' cloud in %s" % CONFIG_PATH
            exit()

        AUTHENTICATION_URL = cloud_conf['url']
        TOKEN = cloud_conf['token']

        cls.ID = "AGKYRATEST" + str(random.random()).split('.')[1]

        cls.LOCAL_ROOT_PATH = "/tmp/" + cls.ID

        cls.settings = SyncerSettings(
            auth_url=AUTHENTICATION_URL,
            auth_token=TOKEN,
            container=cls.ID,
            local_root_path=cls.LOCAL_ROOT_PATH,
            ignore_ssl=True)

        cls.master = PithosFileClient(cls.settings)
        cls.slave = LocalfsFileClient(cls.settings)
        cls.s = FileSyncer(cls.settings, cls.master, cls.slave)
        cls.pithos = cls.master.endpoint
        cls.pithos.create_container(cls.ID)
        cls.db = cls.s.get_db()

    def assert_message(self, mtype):
        m = self.s.get_next_message(block=True)
        print m
        self.assertIsInstance(m, mtype)
        return m

    def assert_no_message(self):
        self.assertIsNone(self.s.get_next_message())

    @classmethod
    def tearDownClass(cls):
        cls.pithos.del_container(delimiter='/')
        cls.pithos.purge_container()

    def get_path(self, f):
        return os.path.join(self.LOCAL_ROOT_PATH, f)

    def test_001_main(self):
        # initial upload to pithos
        f1 = "f001"
        f1_content1 = "content1"
        r1 = self.pithos.upload_from_string(
            f1, f1_content1)
        etag1 = r1['etag']

        state = self.db.get_state(self.s.MASTER, f1)
        self.assertEqual(state.serial, -1)
        self.assertEqual(state.info, {})

        # probe pithos
        self.s.probe_file(self.s.MASTER, f1)
        m = self.assert_message(messaging.UpdateMessage)
        self.assertEqual(m.archive, self.s.MASTER)
        self.assertEqual(m.serial, 0)

        state = self.db.get_state(self.s.MASTER, f1)
        self.assertEqual(state.serial, 0)
        self.assertEqual(state.info["pithos_etag"], etag1)

        # get local state
        state = self.db.get_state(self.s.SLAVE, f1)
        self.assertEqual(state.serial, -1)
        assert state.info == {}

        # sync
        self.s.decide_file_sync(f1)
        dstate = self.db.get_state(self.s.DECISION, f1)
        self.assertEqual(dstate.serial, 0)
        self.assert_message(messaging.SyncMessage)

        # check local synced file
        self.assert_message(messaging.AckSyncMessage)
        state = self.db.get_state(self.s.SLAVE, f1)
        assert state.serial == 0
        info = state.info
        assert info['localfs_size'] == len(f1_content1)
        f1_path = self.get_path(f1)
        self.assertEqual(hash_file(f1_path), utils.hash_string(f1_content1))

        dstate = self.db.get_state(self.s.DECISION, f1)
        sstate = self.db.get_state(self.s.SYNC, f1)
        self.assertEqual(dstate.info, sstate.info)
        self.assertEqual(sstate.serial, 0)

    def test_002_conflict(self):
        fil = "f002"
        # local file
        fil_local_content = "local"
        with open(self.get_path(fil), "w") as f:
            f.write(fil_local_content)

        # upstream
        fil_upstream_content = "upstream"
        r = self.pithos.upload_from_string(
            fil, fil_upstream_content)
        etag = r['etag']

        # cause a conflict
        # first try to upload ignoring upstream changes
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.CollisionMessage)
        self.assert_message(messaging.SyncErrorMessage)

        # this will fail because serial is marked as failed
        self.s.decide_file_sync(fil)
        time.sleep(2)
        self.assert_no_message()

        # now probe upstream too and retry
        self.s.probe_file(self.s.MASTER, fil)
        self.assert_message(messaging.UpdateMessage)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.ConflictStashMessage)
        self.assert_message(messaging.AckSyncMessage)

    def test_003_dirs(self):
        # make local dir with files
        d = "d003"
        d_path = self.get_path(d)
        os.mkdir(d_path)
        fil = "d003/f003"
        f_path = self.get_path(fil)
        f_content = "f2"
        with open(f_path, "w") as f:
            f.write(f_content)
        self.s.probe_file(self.s.SLAVE, d)
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.UpdateMessage)

        self.s.decide_archive(self.s.SLAVE)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        self.assert_message(messaging.AckSyncMessage)

    def test_004_link(self):
        # Check sym links
        fil = "f004"
        f_path = self.get_path(fil)
        open(f_path, 'a').close()
        self.s.probe_file(self.s.SLAVE, fil)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

        ln = "f004.link"
        ln_path = self.get_path(ln)
        os.symlink(f_path, ln_path)
        self.s.probe_file(self.s.SLAVE, ln)
        self.assert_message(messaging.UpdateMessage)
        state = self.db.get_state(self.s.SLAVE, ln)
        self.assertEqual(state.serial, 0)
        self.assertEqual(state.info, {"localfs_type": "unhandled"})
        self.s.decide_file_sync(ln)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        state = self.db.get_state(self.s.MASTER, ln)
        self.assertEqual(state.info, {})

        # Put file upstream to cause conflict
        upstream_ln_content = "regular"
        r = self.pithos.upload_from_string(
            ln, upstream_ln_content)
        etag = r['etag']
        self.s.probe_file(self.s.MASTER, ln)
        self.s.probe_file(self.s.SLAVE, ln)
        self.assert_message(messaging.UpdateMessage)
        state = self.db.get_state(self.s.MASTER, ln)
        self.assertEqual(state.info["pithos_etag"], etag)
        self.s.decide_file_sync(ln)
        self.assert_message(messaging.SyncMessage)
        m = self.assert_message(messaging.ConflictStashMessage)
        stashed_ln = m.stash_name
        self.assert_message(messaging.AckSyncMessage)
        self.assert_no_message()
        self.s.probe_file(self.s.SLAVE, stashed_ln)
        m = self.assert_message(messaging.UpdateMessage)
        self.assertEqual(m.objname, stashed_ln)
        state = self.db.get_state(self.s.SLAVE, stashed_ln)
        self.assertEqual(state.serial, 0)
        self.assertEqual(state.info, {"localfs_type": "unhandled"})
        self.assert_no_message()

        # no changes in linked file
        self.s.probe_file(self.s.SLAVE, fil)
        time.sleep(2)
        self.assert_no_message()

    def test_005_dirs_inhibited_by_file(self):
        fil = "f005"
        f_path = self.get_path(fil)
        open(f_path, 'a').close()
        self.s.probe_file(self.s.SLAVE, fil)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

        r = self.pithos.object_put(
            fil, content_type='application/directory', content_length=0)
        inner_fil = "f005/in005"
        inner_fil_content = "ff1 in dir "
        r1 = self.pithos.upload_from_string(inner_fil, inner_fil_content)
        inner_fil2 = "f005/in2005"
        inner_fil2_content = "inner2 in dir "
        r1 = self.pithos.upload_from_string(inner_fil2, inner_fil2_content)
        self.s.probe_file(self.s.MASTER, fil)
        self.s.probe_file(self.s.MASTER, inner_fil)
        self.s.probe_file(self.s.MASTER, inner_fil2)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.UpdateMessage)

        # fails because file in place of dir
        self.s.decide_file_sync(inner_fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.SyncErrorMessage)

        inner_dir = "f005/indir005"
        r = self.pithos.object_put(
            inner_dir, content_type='application/directory', content_length=0)
        self.s.probe_file(self.s.MASTER, inner_dir)
        self.assert_message(messaging.UpdateMessage)
        # also fails because file in place of dir
        self.s.decide_file_sync(inner_dir)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.SyncErrorMessage)

        # but if we fist sync the dir, it's ok
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        self.s.decide_file_sync(inner_fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

    def test_006_heartbeat(self):
        fil = "f006"
        f_path = self.get_path(fil)
        open(f_path, 'a').close()
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.SyncMessage)
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.HeartbeatNoProbeMessage)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.HeartbeatNoDecideMessage)
        self.assert_message(messaging.AckSyncMessage)
        with open(f_path, 'w') as f:
            f.write("new")
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)

    def test_007_multiprobe(self):
        fil = "f007"
        f_path = self.get_path(fil)
        open(f_path, 'a').close()
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)
        with open(f_path, 'w') as f:
            f.write("new")
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.AlreadyProbedMessage)

    def test_008_dir_contents(self):
        d = "d008"
        d_path = self.get_path(d)
        r = self.pithos.object_put(
            d, content_type='application/directory', content_length=0)
        inner_fil = "d008/inf008"
        inner_fil_content = "fil in dir "
        r1 = self.pithos.upload_from_string(inner_fil, inner_fil_content)
        self.s.probe_file(self.s.MASTER, d)
        m = self.assert_message(messaging.UpdateMessage)
        master_serial = m.serial
        self.assertEqual(master_serial, 0)
        self.s.probe_file(self.s.MASTER, inner_fil)
        self.assert_message(messaging.UpdateMessage)
        # this will also make the dir
        self.s.decide_file_sync(inner_fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        self.assertTrue(os.path.isdir(d_path))
        self.s.probe_file(self.s.SLAVE, d)
        m = self.assert_message(messaging.UpdateMessage)
        slave_serial = m.serial
        self.assertEqual(slave_serial, 1)
        self.s.decide_file_sync(d)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        state = self.db.get_state(self.s.SLAVE, d)
        self.assertEqual(state.serial, master_serial)

if __name__ == '__main__':
    unittest.main()

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
