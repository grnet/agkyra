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

import threading
import logging
from collections import defaultdict
import Queue

from agkyra.syncer import common
from agkyra.syncer.setup import SyncerSettings
from agkyra.syncer.database import TransactedConnection
from agkyra.syncer.localfs_client import LocalfsFileClient
from agkyra.syncer.pithos_client import PithosFileClient
from agkyra.syncer import messaging, utils

logger = logging.getLogger(__name__)


class HandleSyncErrors(object):
    def __init__(self, state, messager, callback=None):
        self.state = state
        self.callback = callback
        self.messager = messager

    def __enter__(self):
        pass

    def __exit__(self, exctype, value, traceback):
        if value is None:
            return
        if not isinstance(value, common.SyncError):
            return False  # re-raise
        hard = isinstance(value, common.HardSyncError)
        if self.callback is not None:
            self.callback(self.state, hard=hard)
        msg = messaging.SyncErrorMessage(
            objname=self.state.objname,
            serial=self.state.serial,
            exception=value, logger=logger)
        self.messager.put(msg)
        return True


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
        self.syncer_dbtuple = settings.syncer_dbtuple
        self.clients = {self.MASTER: master, self.SLAVE: slave}
        self.notifiers = {}
        self.decide_thread = None
        self.sync_threads = []
        self.failed_serials = utils.ThreadSafeDict()
        self.sync_queue = Queue.Queue()
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
                self.notifiers[signature] = client.notifier()
            else:
                logger.info("Notifier %s already up" % signature)

    def stop_notifiers(self, timeout=None):
        for notifier in self.notifiers.values():
            try:
                notifier.stop()
            except KeyError as e:
                # bypass watchdog inotify bug that causes a KeyError
                # when attempting to stop a notifier after the watched
                # directory has been deleted
                logger.warning("Ignored KeyError: %s" % e)
            except TypeError as e:
                # bypass watchdog osx bug that causes a TypeError
                # when attempting to stop a notifier after the watched
                # directory has been deleted
                logger.warning("Ignored TypeError: %s" % e)
        return utils.wait_joins(self.notifiers.values(), timeout)

    def start_decide(self):
        if not self.decide_active:
            self.decide_thread = self._poll_decide()
            logger.info("Started syncing")

    def stop_decide(self, timeout=None):
        if self.decide_active:
            self.decide_thread.stop()
            logger.info("Stopped syncing")
            return utils.wait_joins([self.decide_thread], timeout)
        return timeout

    def stop_all_daemons(self, timeout=None):
        remaining = self.stop_decide(timeout=timeout)
        return self.stop_notifiers(timeout=remaining)

    def wait_sync_threads(self, timeout=None):
        return utils.wait_joins(self.sync_threads, timeout=timeout)

    def get_next_message(self, block=False):
        return self.messager.get(block=block)

    def probe_file(self, archive, objname):
        ident = utils.time_stamp()
        try:
            self._probe_files(archive, [objname], ident)
            client = self.clients[archive]
            client.remove_candidates([objname], ident)
        except common.DatabaseError:
            pass

    def reg_name(self, objname):
        return utils.reg_name(self.settings, objname)

    def _probe_files(self, archive, objnames, ident):
        with TransactedConnection(self.syncer_dbtuple) as db:
            for objname in objnames:
                self._do_probe_file(db, archive, objname, ident)

    def _do_probe_file(self, db, archive, objname, ident):
        logger.debug("Probing archive: %s, object: '%s'" % (archive, objname))
        client = self.clients[archive]
        db_state = db.get_state(archive, objname)
        ref_state = db.get_state(self.SYNC, objname)
        with self.heartbeat.lock() as hb:
            beat = hb.get(self.reg_name(objname))
            if beat is not None:
                beat_thread = beat["thread"]
                if beat_thread is None or beat_thread.is_alive():
                    msg = messaging.HeartbeatNoProbeMessage(
                        archive=archive, objname=objname, heartbeat=beat,
                        logger=logger)
                    self.messager.put(msg)
                    return
        if db_state.serial != ref_state.serial:
            msg = messaging.AlreadyProbedMessage(
                archive=archive, objname=objname, serial=db_state.serial,
                logger=logger)
            self.messager.put(msg)
            return
        live_state = client.probe_file(objname, db_state, ref_state, ident)
        if live_state is not None:
            self.update_file_state(db, live_state)

    def update_file_state(self, db, live_state):
        archive = live_state.archive
        objname = live_state.objname
        serial = live_state.serial
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
        msg = messaging.UpdateMessage(
            archive=archive, objname=objname,
            serial=new_serial, old_serial=serial, logger=logger)
        self.messager.put(msg)
        if new_serial == 0:
            sync_state = common.FileState(
                archive=self.SYNC, objname=objname, serial=-1,
                info={})
            db.put_state(sync_state)

    def dry_run_decisions(self, objnames, master=None, slave=None):
        if master is None:
            master = self.MASTER
        if slave is None:
            slave = self.SLAVE
        decisions = []
        with TransactedConnection(self.syncer_dbtuple) as db:
            for objname in objnames:
                decision = self._dry_run_decision(db, objname, master, slave)
                decisions.append(decision)
        return decisions

    def _dry_run_decision(self, db, objname, master=None, slave=None):
        if master is None:
            master = self.MASTER
        if slave is None:
            slave = self.SLAVE
        ident = utils.time_stamp()
        return self._do_decide_file_sync(db, objname, master, slave, ident, True)

    def decide_file_syncs(self, objnames, master=None, slave=None):
        if master is None:
            master = self.MASTER
        if slave is None:
            slave = self.SLAVE
        ident = utils.time_stamp()
        syncs = []
        try:
            with TransactedConnection(self.syncer_dbtuple) as db:
                for objname in objnames:
                    states = self._decide_file_sync(
                        db, objname, master, slave, ident)
                    if states is not None:
                        syncs.append(states)
        except common.DatabaseError:
            self.clean_heartbeat(objnames, ident)
            return
        self.enqueue_syncs(syncs)

    def decide_file_sync(self, objname, master=None, slave=None):
        if master is None:
            master = self.MASTER
        if slave is None:
            slave = self.SLAVE
        self.decide_file_syncs([objname], master, slave)

    def clean_heartbeat(self, objnames, ident=None):
        with self.heartbeat.lock() as hb:
            for objname in objnames:
                beat = hb.pop(self.reg_name(objname), None)
                if beat is None:
                    return
                if ident and ident != beat["ident"]:
                    hb[self.reg_name(objname)] = beat
                else:
                    logger.debug("cleaning heartbeat %s, object '%s'"
                                 % (beat, objname))

    def _decide_file_sync(self, db, objname, master, slave, ident):
        if not self.settings._sync_is_enabled(db):
            logger.warning("Cannot decide '%s'; sync disabled." % objname)
            return
        states = self._do_decide_file_sync(db, objname, master, slave, ident)
        if states is not None:
            with self.heartbeat.lock() as hb:
                beat = {"ident": ident, "thread": None}
                hb[self.reg_name(objname)] = beat
        return states

    def _do_decide_file_sync(self, db, objname, master, slave, ident,
                             dry_run=False):
        logger.debug("Deciding object: '%s'" % objname)
        master_state = db.get_state(master, objname)
        slave_state = db.get_state(slave, objname)
        sync_state = db.get_state(self.SYNC, objname)
        decision_state = db.get_state(self.DECISION, objname)
        master_serial = master_state.serial
        slave_serial = slave_state.serial
        sync_serial = sync_state.serial
        decision_serial = decision_state.serial

        with self.heartbeat.lock() as hb:
            beat = hb.get(self.reg_name(objname))
            logger.debug("object: %s heartbeat: %s" % (objname, beat))
            if beat is not None:
                if beat["ident"] == ident:
                    logger.warning(
                        "Found used heartbeat ident %s for object %s" %
                        (ident, objname))
                    return None
                beat_thread = beat["thread"]
                if beat_thread is None or beat_thread.is_alive():
                    if not dry_run:
                        msg = messaging.HeartbeatNoDecideMessage(
                            objname=objname, heartbeat=beat, logger=logger)
                        self.messager.put(msg)
                    return None
                if utils.younger_than(beat["ident"],
                                      self.settings.action_max_wait):
                    if not dry_run:
                        msg = messaging.HeartbeatSkipDecideMessage(
                            objname=objname, heartbeat=beat, logger=logger)
                        self.messager.put(msg)
                    return None
                logger.debug("Ignoring previous run: %s %s" %
                             (objname, beat))

        if decision_serial != sync_serial:
            with self.failed_serials.lock() as d:
                failed_sync = d.get((decision_serial, objname))
            if failed_sync is None:
                logger.debug(
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
                if not dry_run:
                    msg = messaging.FailedSyncIgnoreDecisionMessage(
                        objname=objname, serial=decision_serial, logger=logger)
                    self.messager.put(msg)

        if master_serial > sync_serial:
            if master_serial == decision_serial:  # this is a failed serial
                return None
            if not dry_run:
                self._make_decision_state(db, decision_state, master_state)
            return master_state, slave_state, sync_state
        elif master_serial == sync_serial:
            if slave_serial > sync_serial:
                if slave_serial == decision_serial:  # this is a failed serial
                    return None
                if not dry_run:
                    self._make_decision_state(db, decision_state, slave_state)
                return slave_state, master_state, sync_state
            elif slave_serial == sync_serial:
                return None
            else:
                raise AssertionError("Slave serial %s, sync serial %s"
                                     % (slave_serial, sync_serial))

        else:
            raise AssertionError("Master serial %s, sync serial %s"
                                 % (master_serial, sync_serial))

    def _make_decision_state(self, db, decision_state, source_state):
        new_decision_state = decision_state.set(
            serial=source_state.serial, info=source_state.info)
        db.put_state(new_decision_state)

    def enqueue_syncs(self, syncs):
        for sync in syncs:
            self.sync_queue.put(sync)

    def launch_syncs(self):
        with self.heartbeat.lock() as hb:
            alive_threads = len([v for v in hb.values()
                                 if v["thread"] is not None
                                 and v["thread"].is_alive()])
        max_alive_threads = self.settings.max_alive_sync_threads
        new_threads = max_alive_threads - alive_threads
        if new_threads > 0:
            logger.debug("Can start max %s syncs" % new_threads)
            for i in range(new_threads):
                try:
                    tpl = self.sync_queue.get(block=False)
                    self.sync_file(*tpl)
                except Queue.Empty:
                    break

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
        with self.heartbeat.lock() as hb:
            beat = hb.get(self.reg_name(source_state.objname))
            if beat is None:
                raise AssertionError("heartbeat for %s is None" %
                                     source_state.objname)
            assert beat["thread"] is None
            beat["thread"] = thread
        thread.daemon = True
        thread.start()
        self.sync_threads.append(thread)

    def _sync_file(self, source_state, target_state, sync_state):
        clients = self.clients
        source_client = clients[source_state.archive]
        target_client = clients[target_state.archive]
        with HandleSyncErrors(
                source_state, self.messager, self.mark_as_failed):
            source_handle = source_client.stage_file(source_state)
            target_client.start_pulling_file(
                source_handle, target_state, sync_state,
                callback=self.ack_file_sync)

    def mark_as_failed(self, state, hard=False):
        serial = state.serial
        objname = state.objname
        if hard:
            logger.warning(
                "Marking failed serial %s for archive: %s, object: '%s'" %
                (serial, state.archive, objname))
            with self.failed_serials.lock() as d:
                d[(serial, objname)] = state

    def update_state(self, db, old_state, new_state):
        db.put_state(new_state)
        # here we could do any checks needed on the old state,
        # perhaps triggering a probe

    def ack_file_sync(self, synced_source_state, synced_target_state):
        with TransactedConnection(self.syncer_dbtuple) as db:
            self._ack_file_sync(db, synced_source_state, synced_target_state)
        serial = synced_source_state.serial
        objname = synced_source_state.objname
        target = synced_target_state.archive
        self.clean_heartbeat([objname])
        msg = messaging.AckSyncMessage(
            archive=target, objname=objname, serial=serial,
            logger=logger)
        self.messager.put(msg)

    def _ack_file_sync(self, db, synced_source_state, synced_target_state):
        serial = synced_source_state.serial
        objname = synced_source_state.objname
        source = synced_source_state.archive
        target = synced_target_state.archive
        tinfo = synced_target_state.info
        logger.debug("Acking archive: %s, object: '%s', serial: %s "
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
        self.update_state(db, db_source_state, synced_source_state)

        final_target_state = synced_target_state.set(
            serial=serial)
        db_target_state = db.get_state(target, objname)
        self.update_state(db, db_target_state, final_target_state)

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

    def list_deciding(self, archives=None):
        try:
            with TransactedConnection(self.syncer_dbtuple) as db:
                return self._list_deciding(db, archives=archives)
        except common.DatabaseError:
            return set()

    def _list_deciding(self, db, archives=None):
        if archives is None:
            archives = (self.MASTER, self.SLAVE)
        return set(db.list_deciding(archives=archives,
                                    sync=self.SYNC))

    def probe_archive(self, archive, forced=False):
        ident = utils.time_stamp()
        client = self.clients[archive]
        try:
            candidates = client.list_candidate_files(forced=forced)
            self._probe_files(archive, candidates, ident)
            client.remove_candidates(candidates, ident)
        except common.DatabaseError:
            pass

    def decide_archive(self, archive=None):
        try:
            archives = [archive] if archive is not None else None
            objnames = self.list_deciding(archives)
            self.decide_file_syncs(objnames)
            self.launch_syncs()
        except common.DatabaseError:
            pass

    def decide_all_archives(self):
        logger.debug("Checking candidates to sync")
        self.probe_all()
        self.decide_archive()

    def probe_all(self, forced=False):
        self.probe_archive(self.MASTER, forced=forced)
        self.probe_archive(self.SLAVE, forced=forced)

    def _poll_decide(self, interval=3):
        thread = utils.StoppableThread(interval, self.decide_all_archives)
        thread.start()
        return thread

    def check_decisions(self):
        deciding = self.list_deciding()
        decisions = self.dry_run_decisions(deciding)
        by_source = defaultdict(list)
        for decision in decisions:
            source_state = decision[0]
            source = source_state.archive
            objname = source_state.objname
            by_source[source].append(objname)
        return by_source

    # TODO cleanup db of objects deleted in all clients
    # def cleanup(self):
    #     db = self.get_db()
    #     master_deleted = set(db.list_files_with_info(MASTER, {}))
    #     client_deleted = set(db.list_files_with_info(SLAVE, {}))
    #     deleted = master_deleted.intersection(client_deleted)


def conf(auth_url, auth_token, container, local_root_path, **kwargs):
    settings = SyncerSettings(auth_url=auth_url,
                              auth_token=auth_token,
                              container=container,
                              local_root_path=local_root_path,
                              **kwargs)
    master = PithosFileClient(settings)
    slave = LocalfsFileClient(settings)
    return FileSyncer(settings, master, slave)
