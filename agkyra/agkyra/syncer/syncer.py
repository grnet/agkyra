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

import time
import threading
import logging

from agkyra.syncer import common
from agkyra.syncer.setup import SyncerSettings
from agkyra.syncer.database import transaction
from agkyra.syncer.localfs_client import LocalfsFileClient
from agkyra.syncer.pithos_client import PithosFileClient
from agkyra.syncer import messaging, utils

logger = logging.getLogger(__name__)


class FileSyncer(object):

    dbname = None
    clients = None

    def __init__(self, settings, master, slave):
        self.settings = settings
        self.master = master
        self.slave = slave
        self.DECISION = 'DECISION'
        self.SYNC = 'SYNC'
        self.MASTER = master.SIGNATURE
        self.SLAVE = slave.SIGNATURE
        self.get_db = settings.get_db
        self.clients = {self.MASTER: master, self.SLAVE: slave}
        self.notifiers = {}
        self.decide_thread = None
        self.sync_threads = []
        self.failed_serials = common.LockedDict()
        self.messager = settings.messager
        self.heartbeat = self.settings.heartbeat

    def thread_is_active(self, t):
        return t and t.is_alive()

    @property
    def decide_active(self):
        return self.thread_is_active(self.decide_thread)

    @property
    def paused(self):
        return not self.decide_active

    def initiate_probe(self):
        self.start_notifiers()
        self.probe_all(forced=True)

    def start_notifiers(self):
        for signature, client in self.clients.iteritems():
            notifier = self.notifiers.get(signature)
            if not self.thread_is_active(notifier):
                self.notifiers[signature] = \
                    client.notifier(callback=self.probe_file)
            else:
                logger.info("Notifier %s already up" % signature)

    def stop_notifiers(self):
        for notifier in self.notifiers.values():
            notifier.stop()

    def start_decide(self):
        if not self.decide_active:
            self.decide_thread = self._poll_decide()

    def stop_decide(self):
        if self.decide_active:
            self.decide_thread.stop()

    def stop_all_daemons(self):
        self.stop_decide()
        self.stop_notifiers()

    def wait_sync_threads(self):
        for thread in self.sync_threads:
            thread.join()

    def get_next_message(self, block=False):
        return self.messager.get(block=block)

    @transaction()
    def probe_file(self, archive, objname, assumed_info=None):
        logger.info("Probing archive: %s, object: '%s'" % (archive, objname))
        db = self.get_db()
        client = self.clients[archive]
        db_state = db.get_state(archive, objname)
        ref_state = db.get_state(self.SYNC, objname)
        with self.heartbeat.lock() as hb:
            beat = hb.get(objname)
            if beat is not None:
                if utils.younger_than(
                        beat["tstamp"], self.settings.action_max_wait):
                    logger.warning("Object '%s' already handled; "
                                   "Probe aborted." % objname)
                    return
        if db_state.serial != ref_state.serial:
            logger.warning("Serial mismatch in probing archive: %s, "
                           "object: '%s'" % (archive, objname))
            return
        client.start_probing_file(objname, db_state, ref_state,
                                  assumed_info=assumed_info,
                                  callback=self.update_file_state)

    @transaction()
    def update_file_state(self, live_state):
        db = self.get_db()
        archive = live_state.archive
        objname = live_state.objname
        serial = live_state.serial
        msg = messaging.UpdateMessage(
            archive=archive, objname=objname, serial=serial, logger=logger)
        self.messager.put(msg)
        db_state = db.get_state(archive, objname)
        if db_state and db_state.serial != serial:
            logger.warning(
                "Cannot update archive: %s, object: '%s', "
                "serial: %s, db_serial: %s" %
                (archive, objname, serial, db_state.serial))
            return

        new_serial = db.new_serial(objname)
        new_state = live_state.set(serial=new_serial)
        db.put_state(new_state)
        if new_serial == 0:
            sync_state = common.FileState(
                archive=self.SYNC, objname=objname, serial=-1,
                info={})
            db.put_state(sync_state)

    def decide_file_sync(self, objname, master=None, slave=None):
        if master is None:
            master = self.MASTER
        if slave is None:
            slave = self.SLAVE
        ident = utils.time_stamp()
        states = self._decide_file_sync(objname, master, slave, ident)
        if states is None:
            return
        self.sync_file(*states)

    @transaction()
    def _decide_file_sync(self, objname, master, slave, ident):
        states = self._do_decide_file_sync(objname, master, slave, ident)
        if states is not None:
            with self.heartbeat.lock() as hb:
                beat = {"ident": ident, "tstamp": utils.time_stamp()}
                hb.set(objname, beat)
        return states

    def _do_decide_file_sync(self, objname, master, slave, ident):
        db = self.get_db()
        logger.info("Deciding object: '%s'" % objname)
        master_state = db.get_state(master, objname)
        slave_state = db.get_state(slave, objname)
        sync_state = db.get_state(self.SYNC, objname)
        decision_state = db.get_state(self.DECISION, objname)
        master_serial = master_state.serial
        slave_serial = slave_state.serial
        sync_serial = sync_state.serial
        decision_serial = decision_state.serial

        with self.heartbeat.lock() as hb:
            beat = hb.get(objname)
            logger.info("object: %s heartbeat: %s" %
                        (objname, beat))
            if beat is not None:
                if beat["ident"] == ident:
                    logger.info("Found heartbeat with current ident %s"
                                % ident)
                else:
                    if utils.younger_than(
                            beat["tstamp"], self.settings.action_max_wait):
                        logger.warning("Object '%s' already handled; aborting."
                                       % objname)
                        return None
                    logger.warning("Ignoring previous run: %s %s" %
                                   (objname, beat))

        if decision_serial != sync_serial:
            failed_sync = self.failed_serials.get((decision_serial, objname))
            if failed_sync is None:
                logger.warning(
                    "Already decided: '%s', decision: %s, sync: %s" %
                    (objname, decision_serial, sync_serial))
                if decision_serial == master_serial:
                    return master_state, slave_state, sync_state
                elif decision_serial == slave_serial:
                    return slave_state, master_state, sync_state
                else:
                    raise AssertionError(
                        "Decision serial %s for objname '%s' "
                        "does not match any archive." %
                        (decision_serial, objname))
            else:
                logger.warning(
                    "Ignoring failed decision for: '%s', decision: %s" %
                    (objname, decision_serial))

        if master_serial > sync_serial:
            self._make_decision_state(decision_state, master_state)
            return master_state, slave_state, sync_state
        elif master_serial == sync_serial:
            if slave_serial > sync_serial:
                self._make_decision_state(decision_state, slave_state)
                return slave_state, master_state, sync_state
            elif slave_serial == sync_serial:
                return None
            else:
                raise AssertionError("Slave serial %s, sync serial %s"
                                     % (slave_serial, sync_serial))

        else:
            raise AssertionError("Master serial %s, sync serial %s"
                                 % (master_serial, sync_serial))

    def _make_decision_state(self, decision_state, source_state):
        db = self.get_db()
        new_decision_state = decision_state.set(
            serial=source_state.serial, info=source_state.info)
        db.put_state(new_decision_state)

    def sync_file(self, source_state, target_state, sync_state):
        msg = messaging.SyncMessage(
            objname=source_state.objname,
            archive=source_state.archive,
            serial=source_state.serial,
            info=source_state.info,
            logger=logger)
        self.messager.put(msg)
        thread = threading.Thread(
            target=self._sync_file,
            args=(source_state, target_state, sync_state))
        thread.start()
        self.sync_threads.append(thread)

    def _sync_file(self, source_state, target_state, sync_state):
        clients = self.clients
        source_client = clients[source_state.archive]
        try:
            source_handle = source_client.stage_file(source_state)
        except common.SyncError as e:
            logger.warning(e)
            return
        target_client = clients[target_state.archive]
        target_client.start_pulling_file(
            source_handle, target_state, sync_state,
            callback=self.ack_file_sync,
            failure_callback=self.mark_as_failed)

    def mark_as_failed(self, state):
        serial = state.serial
        objname = state.objname
        logger.warning(
            "Marking failed serial %s for archive: %s, object: '%s'" %
            (serial, state.archive, objname))
        with self.heartbeat.lock() as hb:
            hb.delete(objname)
        self.failed_serials.put((serial, objname), state)

    def update_state(self, old_state, new_state):
        db = self.get_db()
        db.put_state(new_state)
        # here we could do any checks needed on the old state,
        # perhaps triggering a probe

    def ack_file_sync(self, synced_source_state, synced_target_state):
        self._ack_file_sync(synced_source_state, synced_target_state)
        serial = synced_source_state.serial
        objname = synced_source_state.objname
        target = synced_target_state.archive
        with self.heartbeat.lock() as hb:
            hb.delete(objname)
        msg = messaging.AckSyncMessage(
            archive=target, objname=objname, serial=serial,
            logger=logger)
        self.messager.put(msg)

    @transaction()
    def _ack_file_sync(self, synced_source_state, synced_target_state):
        db = self.get_db()
        serial = synced_source_state.serial
        objname = synced_source_state.objname
        source = synced_source_state.archive
        target = synced_target_state.archive
        tinfo = synced_target_state.info
        logger.info("Acking archive: %s, object: '%s', serial: %s "
                    "info: %s" %
                    (target, objname, serial, tinfo))
        decision_state = db.get_state(self.DECISION, objname)
        sync_state = db.get_state(self.SYNC, objname)

        if serial != decision_state.serial:
            raise AssertionError(
                "Serial mismatch: assumed sync %s, decision %s"
                % (serial, decision_state.serial))
        if serial <= sync_state.serial:
            raise common.SyncError(
                "cannot ack: serial %s < sync serial %s" %
                (serial, sync_state.serial))

        db_source_state = db.get_state(source, objname)
        self.update_state(db_source_state, synced_source_state)

        final_target_state = synced_target_state.set(
            serial=serial)
        db_target_state = db.get_state(target, objname)
        self.update_state(db_target_state, final_target_state)

        sync_info = dict(synced_source_state.info)
        sync_info.update(synced_target_state.info)
        # The 'info' namespace is global. Some attributes may be globally
        # recognizable by all clients with the same semantics, such as
        # a content-hash (e.g. SHA256), while other may be specific to
        # each client. Clients are responsible to protect their private
        # attributes creating their own namespace, for example
        # 'localfs_mtime', 'object_store_etag'
        new_sync_state = sync_state.set(serial=serial, info=sync_info)
        db.put_state(new_sync_state)
        new_decision_state = new_sync_state.set(archive=self.DECISION)
        db.put_state(new_decision_state)

    @transaction()
    def list_deciding(self, archives=None):
        db = self.get_db()
        if archives is None:
            archives = (self.MASTER, self.SLAVE)
        return set(db.list_deciding(archives=archives,
                                    sync=self.SYNC))

    def probe_archive(self, archive, forced=False):
        client = self.clients[archive]
        candidates = client.list_candidate_files(forced=forced)
        for objname in candidates:
            self.probe_file(archive, objname)

    def decide_archive(self, archive):
        for objname in self.list_deciding([archive]):
            self.decide_file_sync(objname)

    def decide_all_archives(self):
        logger.info("Checking candidates to sync")
        self.probe_all()
        for objname in self.list_deciding():
            self.decide_file_sync(objname)

    def probe_all(self, forced=False):
        self.probe_archive(self.MASTER, forced=forced)
        self.probe_archive(self.SLAVE, forced=forced)

    def _poll_decide(self, interval=3):
        class DecideThread(utils.StoppableThread):
            def run_body(this):
                self.decide_all_archives()
                time.sleep(interval)
        return utils.start_daemon(DecideThread)

    # TODO cleanup db of objects deleted in all clients
    # def cleanup(self):
    #     db = self.get_db()
    #     master_deleted = set(db.list_files_with_info(MASTER, {}))
    #     client_deleted = set(db.list_files_with_info(SLAVE, {}))
    #     deleted = master_deleted.intersection(client_deleted)


def conf(instance, auth_url, auth_token, container, local_root_path, **kwargs):
    settings = SyncerSettings(instance=instance,
                              auth_url=auth_url,
                              auth_token=auth_token,
                              container=container,
                              local_root_path=local_root_path,
                              **kwargs)
    master = PithosFileClient(settings)
    slave = LocalfsFileClient(settings)
    return FileSyncer(settings, master, slave)
