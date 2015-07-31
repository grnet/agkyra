# -*- coding: utf-8 -*-

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

from __future__ import unicode_literals

from agkyra.syncer.setup import SyncerSettings
from agkyra.syncer import localfs_client
from agkyra.syncer.pithos_client import PithosFileClient
from agkyra.syncer.syncer import FileSyncer
import agkyra.syncer.syncer
from agkyra.syncer import messaging, utils, common
import random
import os
import time
import shutil
import unittest
import mock
import sqlite3
import tempfile

from functools import wraps
from agkyra.config import AgkyraConfig, CONFIG_PATH
from kamaki.clients import ClientError

import logging
logger = logging.getLogger('agkyra')
handler = logging.StreamHandler()
formatter = logging.Formatter("%(levelname)s:%(asctime)s:%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# kamakisend_logger = logging.getLogger('kamaki.clients.send')
# kamakisend_logger.addHandler(handler)
# kamakisend_logger.setLevel(logging.DEBUG)
# kamakirecv_logger = logging.getLogger('kamaki.clients.recv')
# kamakirecv_logger.addHandler(handler)
# kamakirecv_logger.setLevel(logging.DEBUG)

TMP = os.path.realpath(tempfile.gettempdir())


def hash_file(fil):
    with open(fil) as f:
        return utils.hash_string(f.read())


def mock_transaction(max_wait=60, init_wait=0.4, exp_backoff=1.1):
    def wrap(func):
        @wraps(func)
        def inner(*args, **kwargs):
            print "IN MOCK"
            obj = args[0]
            db = obj.get_db()
            attempt = 0
            current_max_wait = init_wait
            db.begin()
            r = func(*args, **kwargs)
            raise common.DatabaseError()
        return inner
    return wrap


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

        cls.ID = "ΑΓΚΥΡΑTEST" + str(random.random()).split('.')[1]

        cls.LOCAL_ROOT_PATH = utils.join_path(TMP, cls.ID)

        cls.settings = SyncerSettings(
            auth_url=AUTHENTICATION_URL,
            auth_token=TOKEN,
            container=cls.ID,
            local_root_path=cls.LOCAL_ROOT_PATH,
            ignore_ssl=True)

        cls.master = PithosFileClient(cls.settings)
        cls.slave = localfs_client.LocalfsFileClient(cls.settings)
        cls.s = FileSyncer(cls.settings, cls.master, cls.slave)
        cls.pithos = cls.master.endpoint
        cls.pithos.create_container(cls.ID)
        cls.db = cls.s.get_db()
        m = cls.s.get_next_message(block=True)
        assert isinstance(m, messaging.PithosSyncEnabled)
        m = cls.s.get_next_message(block=True)
        assert isinstance(m, messaging.LocalfsSyncEnabled)

    def assert_message(self, mtype):
        m = self.s.get_next_message(block=True)
        print m
        self.assertIsInstance(m, mtype)
        return m

    def assert_messages(self, mtypes_dict):
        while mtypes_dict:
            m = self.s.get_next_message(block=True)
            print m
            mtype = m.__class__
            num = mtypes_dict.get(mtype, 0)
            if not num:
                raise AssertionError("Got unexpected message %s" % m)
            new_num = num -1
            if new_num:
                mtypes_dict[mtype] = new_num
            else:
                mtypes_dict.pop(mtype)

    def assert_no_message(self):
        self.assertIsNone(self.s.get_next_message())

    @classmethod
    def tearDownClass(cls):
        cls.pithos.del_container(delimiter='/')
        cls.pithos.purge_container()

    def get_path(self, f):
        return os.path.join(self.LOCAL_ROOT_PATH, f)

    def test_0001_listing_local(self):
        def real(candidates):
            return [c for c in candidates
                    if not c.startswith(self.settings.cache_name)]

        candidates = self.slave.list_candidate_files()
        self.assertEqual(candidates, [])
        candidates = self.slave.list_candidate_files(forced=True)
        self.assertEqual(real(candidates), [])

        fil = "φ0001"
        f_path = self.get_path(fil)
        open(f_path, "a").close()
        d = "δ0001"
        d_path = self.get_path(d)
        os.mkdir(d_path)

        candidates = self.slave.list_candidate_files(forced=True)
        self.assertEqual(sorted(real(candidates)), sorted([fil, d]))
        self.s.probe_archive(self.s.SLAVE)
        self.assert_messages(
            {messaging.UpdateMessage: 2,
             messaging.IgnoreProbeMessage: 4})

        with self.slave.probe_candidates.lock() as dct:
            self.assertNotIn(fil, dct)
            self.assertNotIn(d, dct)

        self.s.decide_archive(self.s.SLAVE)
        self.assert_messages({
            messaging.SyncMessage: 2,
            messaging.AckSyncMessage: 2})

        os.unlink(f_path)

        with mock.patch(
                "agkyra.syncer.localfs_client.LocalfsFileClient.list_files") as mk:
            mk.return_value = []
            candidates = self.slave.list_candidate_files(forced=True)
            self.assertEqual(real(candidates), [d])

        candidates = self.slave.list_candidate_files(forced=True)
        self.assertEqual(sorted(real(candidates)), sorted([fil, d]))

        candidates = self.slave.list_candidate_files()
        self.assertEqual(sorted(real(candidates)), sorted([fil, d]))

        self.slave.remove_candidates(candidates, None)
        candidates = self.slave.list_candidate_files()
        self.assertEqual(candidates, [])

    def test_0002_notifier_local(self):
        f_out = "φ0002out"
        f_cache = "φ0002cache"
        f_upd = "φ0002upd"
        f_ren = "φ0002ren"
        f_cached = "φ0002cached"
        dbefore = "δ0002before"
        f_out_path = self.get_path(f_out)
        f_cache_path = self.get_path(f_cache)
        f_upd_path = self.get_path(f_upd)
        f_ren_path = self.get_path(f_ren)
        f_cached_path = os.path.join(
            self.settings.cache_path, f_cached)
        dbefore_path = self.get_path(dbefore)
        open(f_out_path, "a").close()
        open(f_cache_path, "a").close()
        open(f_upd_path, "a").close()
        open(f_ren_path, "a").close()
        open(f_cached_path, "a").close()
        os.mkdir(dbefore_path)

        notifier = self.slave.notifier()
        candidates = self.slave.list_candidate_files()
        self.assertEqual(candidates, [])

        fafter = "φ0002after"
        fafter_path = self.get_path(fafter)
        dafter = "δ0002after"
        dafter_path = self.get_path(dafter)
        open(fafter_path, "a").close()
        os.mkdir(dafter_path)

        time.sleep(1)
        candidates = self.slave.list_candidate_files()
        self.assertEqual(sorted(candidates), sorted([fafter, dafter]))

        os.rename(f_cache_path,
                  utils.join_path(self.settings.cache_path, f_cache))
        os.rename(f_out_path,
                  utils.join_path(TMP, f_out))
        with open(f_upd_path, "a") as f:
            f.write("upd")

        f_in = "φ0002in"
        f_in_path = self.get_path(f_in)
        f_in_orig_path = utils.join_path(TMP, f_in)
        open(f_in_orig_path, "a").close()
        os.rename(f_in_orig_path, f_in_path)

        f_ren_new = "φ0002ren_new"
        f_ren_new_path = self.get_path(f_ren_new)
        os.rename(f_ren_path, f_ren_new_path)

        f_cached_out_path = self.get_path(f_cached)
        os.rename(f_cached_path, f_cached_out_path)

        time.sleep(1)
        candidates = self.slave.list_candidate_files()
        self.assertEqual(sorted(candidates),
                         sorted([fafter, dafter,
                                 f_in, f_out, f_upd,
                                 f_ren, f_ren_new,
                                 f_cache, f_cached]))
        notifier.stop()

    def test_001_probe_and_sync(self):
        # initial upload to pithos
        f1 = "φ001"
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
        fil = "φ002"
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
        self.assert_message(messaging.FailedSyncIgnoreDecisionMessage)

        # now probe upstream too and retry
        self.s.probe_file(self.s.MASTER, fil)
        self.assert_message(messaging.UpdateMessage)
        self.s.start_notifiers()
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.FailedSyncIgnoreDecisionMessage)
        self.assert_message(messaging.SyncMessage)
        m = self.assert_message(messaging.ConflictStashMessage)
        stash_name = m.stash_name
        self.assert_message(messaging.AckSyncMessage)
        time.sleep(1)
        self.s.stop_notifiers()
        local_cands = self.slave.list_candidate_files()
        self.assertIn(stash_name, local_cands)

    def test_003_dirs(self):
        # make local dir with files
        d = "δ003"
        d_path = self.get_path(d)
        os.mkdir(d_path)
        fil = "δ003/φ003"
        f_path = self.get_path(fil)
        f_content = "f2"
        with open(f_path, "w") as f:
            f.write(f_content)
        self.s.probe_file(self.s.SLAVE, d)
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.UpdateMessage)

        self.s.decide_archive(self.s.SLAVE)
        self.assert_messages({
            messaging.SyncMessage: 2,
            messaging.AckSyncMessage: 2})

    def test_004_link(self):
        # Check sym links
        fil = "φ004"
        f_path = self.get_path(fil)
        open(f_path, 'a').close()
        self.s.probe_file(self.s.SLAVE, fil)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

        ln = "φ004.link"
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
        fil = "φ005"
        f_path = self.get_path(fil)
        open(f_path, 'a').close()
        self.s.probe_file(self.s.SLAVE, fil)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

        r = self.pithos.object_put(
            fil, content_type='application/directory', content_length=0)
        inner_fil = "φ005/in005"
        inner_fil_content = "ff1 in dir "
        r1 = self.pithos.upload_from_string(inner_fil, inner_fil_content)
        self.s.probe_file(self.s.MASTER, fil)
        self.s.probe_file(self.s.MASTER, inner_fil)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.UpdateMessage)

        # fails because file in place of dir
        self.s.decide_file_sync(inner_fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.SyncErrorMessage)

        inner_dir = "φ005/indir005"
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
        self.assertTrue(os.path.isdir(f_path))
        self.s.decide_file_sync(inner_fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

    def test_006_heartbeat(self):
        fil = "φ006"
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

        with mock.patch(
                "agkyra.syncer.database.SqliteFileStateDB.commit") as dbmock:
            dbmock.side_effect = [sqlite3.OperationalError("locked"),
                                  common.DatabaseError()]
            self.s.decide_file_sync(fil)
        self.assert_message(messaging.HeartbeatReplayDecideMessage)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.HeartbeatNoDecideMessage)
        print "SLEEPING 11"
        time.sleep(11)
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

    def test_007_multiprobe(self):
        fil = "φ007"
        f_path = self.get_path(fil)
        open(f_path, 'a').close()
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)
        with open(f_path, 'w') as f:
            f.write("new")
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.AlreadyProbedMessage)

    def test_008_dir_contents(self):
        d = "δ008"
        d_path = self.get_path(d)
        r = self.pithos.object_put(
            d, content_type='application/directory', content_length=0)
        inner_fil = "δ008/inφ008"
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
        # sync the dir too
        self.s.probe_file(self.s.SLAVE, d)
        m = self.assert_message(messaging.UpdateMessage)
        slave_serial = m.serial
        self.assertEqual(slave_serial, 1)
        self.s.decide_file_sync(d)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        state = self.db.get_state(self.s.SLAVE, d)
        self.assertEqual(state.serial, master_serial)

        # locally remove the dir and sync
        shutil.rmtree(d_path)
        self.s.probe_file(self.s.SLAVE, d)
        self.s.probe_file(self.s.SLAVE, inner_fil)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.UpdateMessage)
        self.s.decide_file_sync(d)
        self.s.decide_file_sync(inner_fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        with self.assertRaises(ClientError) as cm:
            self.pithos.get_object_info(d)
        self.assertEqual(cm.exception.status, 404)

    def test_009_dir_delete_upstream(self):
        d = "δ009"
        d_path = self.get_path(d)
        r = self.pithos.object_put(
            d, content_type='application/directory', content_length=0)
        innerd = "δ009/innerδ009"
        r = self.pithos.object_put(
            innerd, content_type='application/directory', content_length=0)
        self.s.probe_file(self.s.MASTER, d)
        self.s.probe_file(self.s.MASTER, innerd)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.UpdateMessage)
        self.s.decide_file_sync(d)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        self.s.decide_file_sync(innerd)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        self.assertTrue(os.path.isdir(d_path))

        # delete upstream
        self.pithos.del_object(d)
        self.pithos.del_object(innerd)
        self.s.probe_file(self.s.MASTER, d)
        self.s.probe_file(self.s.MASTER, innerd)
        self.assert_message(messaging.UpdateMessage)
        self.assert_message(messaging.UpdateMessage)

        # will fail because local dir is non-empty
        self.s.decide_file_sync(d)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.SyncErrorMessage)

        # but this is ok
        self.s.decide_file_sync(innerd)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)
        self.s.decide_file_sync(d)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

    def test_010_live_update_local(self):
        fil = "φ010"
        f_path = self.get_path(fil)
        with open(f_path, "w") as f:
            f.write("f to be changed")

        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)
        state = self.db.get_state(self.s.SLAVE, fil)
        f_info = state.info

        f_content = "changed"
        with open(f_path, "w") as f:
            f.write(f_content)

        self.s.decide_file_sync(fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.LiveInfoUpdateMessage)
        self.assert_message(messaging.AckSyncMessage)

        state = self.db.get_state(self.s.SLAVE, fil)
        new_info = state.info
        self.assertNotEqual(f_info, new_info)
        self.assertEqual(new_info["localfs_size"], len(f_content))

    def test_011_live_update_upstream(self):
        fil = "φ011"
        f_path = self.get_path(fil)
        r = self.pithos.upload_from_string(fil, "f upstream")
        etag = r['etag']

        self.s.probe_file(self.s.MASTER, fil)
        self.assert_message(messaging.UpdateMessage)
        state = self.db.get_state(self.s.MASTER, fil)
        f_info = state.info
        self.assertEqual(f_info["pithos_etag"], etag)

        r1 = self.pithos.upload_from_string(fil, "new")
        new_etag = r1['etag']

        self.s.decide_file_sync(fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.LiveInfoUpdateMessage)
        self.assert_message(messaging.AckSyncMessage)
        state = self.db.get_state(self.s.MASTER, fil)
        new_info = state.info
        self.assertEqual(new_info["pithos_etag"], new_etag)

    def test_012_cachename(self):
        fil = "φ012"
        f_path = self.get_path(fil)
        with open(f_path, "w") as f:
            f.write("content")

        state = self.db.get_state(self.s.SLAVE, fil)
        handle = localfs_client.LocalfsTargetHandle(self.s.settings, state)
        hidden_filename = utils.join_path(
            handle.cache_hide_name, utils.hash_string(handle.objname))
        hidden_path = handle.get_path_in_cache(hidden_filename)
        self.assertFalse(os.path.isfile(hidden_path))

        self.assertIsNone(self.db.get_cachename(hidden_filename))
        handle.move_file()

        self.assertTrue(os.path.isfile(hidden_path))
        self.assertIsNotNone(self.db.get_cachename(hidden_filename))
        handle.move_file()
        self.assertTrue(os.path.isfile(hidden_path))

        shutil.move(hidden_path, f_path)
        self.assertIsNotNone(self.db.get_cachename(hidden_filename))
        handle.move_file()
        self.assertTrue(os.path.isfile(hidden_path))

        # open file to cause busy error
        f = open(hidden_path, "r")
        with self.assertRaises(common.BusyError):
            handle.hide_file()

    def test_013_collisions(self):
        fil = "φ013"
        f_path = self.get_path(fil)
        with open(f_path, "w") as f:
            f.write("content")
        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)

        r = self.pithos.upload_from_string(fil, "new")
        self.s.decide_file_sync(fil)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.CollisionMessage)
        self.assert_message(messaging.SyncErrorMessage)

        d = "δ013"
        d_path = self.get_path(d)
        os.mkdir(d_path)
        self.s.probe_file(self.s.SLAVE, d)
        self.assert_message(messaging.UpdateMessage)

        r = self.pithos.upload_from_string(d, "new")
        self.s.decide_file_sync(d)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.CollisionMessage)
        self.assert_message(messaging.SyncErrorMessage)

        d_synced = "δ013_s"
        d_synced_path = self.get_path(d_synced)
        os.mkdir(d_synced_path)
        self.s.probe_file(self.s.SLAVE, d_synced)
        self.assert_message(messaging.UpdateMessage)
        self.s.decide_file_sync(d_synced)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.AckSyncMessage)

        os.rmdir(d_synced_path)
        self.s.probe_file(self.s.SLAVE, d_synced)
        self.assert_message(messaging.UpdateMessage)

        r = self.pithos.upload_from_string(d_synced, "new")
        self.s.decide_file_sync(d_synced)
        self.assert_message(messaging.SyncMessage)
        self.assert_message(messaging.CollisionMessage)
        self.assert_message(messaging.SyncErrorMessage)

    def test_014_staging(self):
        fil = "φ014"
        d = "δ014"
        fln = "φ014.link"
        f_path = self.get_path(fil)
        with open(f_path, "w") as f:
            f.write("content")
        fln_path = self.get_path(fln)
        os.symlink(f_path, fln_path)
        d_path = self.get_path(d)
        os.mkdir(d_path)

        self.s.probe_file(self.s.SLAVE, fil)
        self.assert_message(messaging.UpdateMessage)
        state = self.db.get_state(self.s.SLAVE, fil)
        handle = localfs_client.LocalfsSourceHandle(self.s.settings, state)
        staged_path = handle.staged_path
        self.assertTrue(localfs_client.files_equal(f_path, staged_path))
        handle.unstage_file()
        self.assertFalse(os.path.exists(staged_path))

        with open(f_path, "w") as f:
            f.write("content new")
        handle = localfs_client.LocalfsSourceHandle(self.s.settings, state)
        self.assert_message(messaging.LiveInfoUpdateMessage)
        self.assertTrue(localfs_client.files_equal(f_path, staged_path))
        handle.unstage_file()

        f = open(f_path, "r")
        with self.assertRaises(common.OpenBusyError):
            handle = localfs_client.LocalfsSourceHandle(self.s.settings, state)

        ftmp_path = self.get_path("φ014tmp")
        with open(ftmp_path, "w") as f:
            f.write("tmp")
        os.unlink(f_path)
        os.symlink(ftmp_path, f_path)
        state = self.db.get_state(self.s.SLAVE, fil)
        handle = localfs_client.LocalfsSourceHandle(self.s.settings, state)
        self.assert_message(messaging.LiveInfoUpdateMessage)
        self.assertIsNone(handle.staged_path)

        self.s.probe_file(self.s.SLAVE, fln)
        self.assert_message(messaging.UpdateMessage)
        state = self.db.get_state(self.s.SLAVE, fln)
        handle = localfs_client.LocalfsSourceHandle(self.s.settings, state)
        self.assertIsNone(handle.staged_path)

        os.unlink(fln_path)
        with open(fln_path, "w") as f:
            f.write("reg file")

        handle = localfs_client.LocalfsSourceHandle(self.s.settings, state)
        self.assertIsNone(handle.staged_path)

        # try to stage now
        handle.stage_file()
        self.assert_message(messaging.LiveInfoUpdateMessage)
        self.assertTrue(localfs_client.files_equal(
            fln_path, handle.staged_path))
        handle.unstage_file()

        fmissing = "fmissing014"
        fmissing_path = self.get_path(fmissing)
        self.s.probe_file(self.s.SLAVE, fmissing)
        state = self.db.get_state(self.s.SLAVE, fmissing)
        handle = localfs_client.LocalfsSourceHandle(self.s.settings, state)
        self.assertIsNone(handle.staged_path)

        with open(fmissing_path, "w") as f:
            f.write("ref file")

        handle.copy_file()
        self.assertIsNotNone(handle.staged_path)
        live_info = localfs_client.get_live_info(
            self.s.settings, handle.fspath)
        handle.check_staged(live_info)

        with open(fmissing_path, "w") as f:
            f.write("ref file2")
        with self.assertRaises(common.ChangedBusyError):
            handle.check_staged(live_info)

        # turn it into a dir
        os.unlink(fmissing_path)
        os.mkdir(fmissing_path)
        handle.copy_file()
        with self.assertRaises(common.NotStableBusyError):
            handle.check_staged(live_info)

        # info of dir
        live_info = localfs_client.get_live_info(
            self.s.settings, handle.fspath)
        handle.check_staged(live_info)


if __name__ == '__main__':
    unittest.main()
