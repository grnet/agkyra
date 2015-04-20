import time
import threading
import logging
import re
import os

from agkyra.syncer import common
from agkyra.syncer.setup import SyncerSettings
from agkyra.syncer.database import transaction
from agkyra.syncer.localfs_client import LocalfsFileClient
from agkyra.syncer.pithos_client import PithosFileClient

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class IgnoreKamakiInfo(logging.Filter):
    def filter(self, record):
        return not (record.name.startswith('kamaki') and
                    record.levelno <= logging.INFO)

for handler in logging.root.handlers:
    handler.addFilter(IgnoreKamakiInfo())


exclude_regexes = ["\.#", "\.~", "~\$", "~.*\.tmp$", "\..*\.swp$"]
exclude_pattern = re.compile('|'.join(exclude_regexes))


class FileSyncer(object):

    dbname = None
    clients = None

    def __init__(self, settings, master, slave):
        self.settings = settings
        self.master = master
        self.slave = slave
        self.DECISION = 'DECISION'
        self.SYNC = 'SYNC'
        self.MASTER = master.NAME
        self.SLAVE = slave.NAME
        self.get_db = settings.get_db
        self.clients = {self.MASTER: master, self.SLAVE: slave}
        self.decide_event = None
        self.failed_serials = common.LockedDict()

    @property
    def paused(self):
        return (not self.decide_event.is_set()) if self.decide_event else True

    def launch_daemons(self):
        self.start_notifiers()
        self.start_decide()

    def start_notifiers(self):
        self.notifiers = {
            self.MASTER: self.master.notifier(callback=self.probe_path),
            self.SLAVE: self.slave.notifier(callback=self.probe_path),
            }

    def start_decide(self):
        if self.decide_event is None:
            self.decide_event = self._poll_decide()
        self.decide_event.set()

    def pause_decide(self):
        if self.decide_event is not None:
            self.decide_event.clear()

    def exclude_path(self, path):
        parts = path.split(os.path.sep)
        init_part = parts[0]
        if init_part in [self.settings.cache_name]:
            return True
        final_part = parts[-1]
        return exclude_pattern.match(final_part)

    @transaction()
    def probe_path(self, archive, path):
        if self.exclude_path(path):
            logger.warning("Ignoring probe archive: %s, path: %s" %
                           (archive, path))
            return
        logger.info("Probing archive: %s, path: '%s'" % (archive, path))
        db = self.get_db()
        client = self.clients[archive]
        db_state = db.get_state(archive, path)
        ref_state = db.get_state(self.SYNC, path)
        if db_state.serial != ref_state.serial:
            logger.warning("Serial mismatch in probing archive: %s, path: '%s'"
                           % (archive, path))
            return
        client.start_probing_path(path, db_state, ref_state,
                                  callback=self.update_path)

    @transaction()
    def update_path(self, live_state):
        db = self.get_db()
        archive = live_state.archive
        path = live_state.path
        serial = live_state.serial
        if self.exclude_path(path):
            logger.warning("Ignoring update archive: %s, path: %s" %
                           (archive, path))
            return
        logger.info("Updating archive: %s, path: '%s', serial: %s" %
                    (archive, path, serial))
        db_state = db.get_state(archive, path)
        if db_state and db_state.serial != serial:
            logger.warning(
                "Cannot update archive: %s, path: '%s', "
                "serial: %s, db_serial: %s" %
                (archive, path, serial, db_state.serial))
            return

        new_serial = db.new_serial(path)
        new_state = live_state.set(serial=new_serial)
        db.put_state(new_state)
        if new_serial == 0:
            sync_state = common.FileState(
                archive=self.SYNC, path=path, serial=-1,
                info={})
            db.put_state(sync_state)

    def decide_path(self, path, master=None, slave=None):
        if master is None:
            master = self.MASTER
        if slave is None:
            slave = self.SLAVE
        states = self._decide_path(path, master, slave)
        if states is None:
            return
        self.sync_path(*states)

    @transaction()
    def _decide_path(self, path, master, slave):
        db = self.get_db()
        logger.info("Deciding path: '%s'" % path)
        master_state = db.get_state(master, path)
        slave_state = db.get_state(slave, path)
        sync_state = db.get_state(self.SYNC, path)
        decision_state = db.get_state(self.DECISION, path)
        master_serial = master_state.serial
        slave_serial = slave_state.serial
        sync_serial = sync_state.serial
        decision_serial = decision_state.serial

        if decision_serial != sync_serial:
            failed_sync = self.failed_serials.get((decision_serial, path))
            if failed_sync is None:
                logger.warning(
                    "Already decided: '%s', decision: %s, sync: %s" %
                    (path, decision_serial, sync_serial))
                if decision_serial == master_serial:
                    return master_state, slave_state, sync_state
                elif decision_serial == slave_serial:
                    return slave_state, master_state, sync_state
                else:
                    raise AssertionError(
                        "Decision serial %s for path '%s' "
                        "does not match any archive." %
                        (decision_serial, path))
            else:
                logger.warning(
                    "Ignoring failed decision for: '%s', decision: %s" %
                    (path, decision_serial))

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

    def sync_path(self, source_state, target_state, sync_state):
        logger.info("Syncing archive: %s, path: '%s', serial: %s" %
                    (source_state.archive,
                     source_state.path,
                     source_state.serial))
        thread = threading.Thread(
            target=self._sync_path,
            args=(source_state, target_state, sync_state))
        thread.start()

    def _sync_path(self, source_state, target_state, sync_state):
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
            callback=self.acknowledge_path,
            failure_callback=self.mark_as_failed)

    def mark_as_failed(self, state):
        serial = state.serial
        path = state.path
        logger.warning(
            "Marking failed serial %s for archive: %s, path: '%s'" %
            (serial, state.archive, path))
        self.failed_serials.put((serial, path), state)

    def update_state(self, old_state, new_state):
        db = self.get_db()
        db.put_state(new_state)
        # here we could do any checks needed on the old state,
        # perhaps triggering a probe

    @transaction()
    def acknowledge_path(self, synced_source_state, synced_target_state):
        db = self.get_db()
        serial = synced_source_state.serial
        path = synced_source_state.path
        source = synced_source_state.archive
        target = synced_target_state.archive
        logger.info("Acking archive: %s, path: '%s', serial: %s" %
                    (target, path, serial))

        decision_state = db.get_state(self.DECISION, path)
        sync_state = db.get_state(self.SYNC, path)

        if serial != decision_state.serial:
            raise AssertionError(
                "Serial mismatch: assumed sync %s, decision %s"
                % (serial, decision_state.serial))
        if serial <= sync_state.serial:
            raise common.SyncError(
                "cannot ack: serial %s < sync serial %s" %
                (serial, sync_state.serial))

        db_source_state = db.get_state(source, path)
        self.update_state(db_source_state, synced_source_state)

        final_target_state = synced_target_state.set(
            serial=serial)
        db_target_state = db.get_state(target, path)
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
        return list(db.list_deciding(archives=archives,
                                     sync=self.SYNC))

    def probe_archive(self, archive):
        client = self.clients[archive]
        for path in client.list_candidate_files():
            self.probe_path(archive, path)

    def decide_archive(self, archive):
        for path in self.list_deciding([archive]):
            self.decide_path(path)

    def decide_all_archives(self):
        logger.info("Checking candidates to sync")
        for path in self.list_deciding():
            self.decide_path(path)

    def probe_and_sync_all(self):
        self.probe_archive(self.MASTER)
        self.probe_archive(self.SLAVE)
        for path in self.list_deciding():
            self.decide_path(path)

    def _poll_decide(self, interval=3):
        event = threading.Event()

        def go():
            while True:
                event.wait()
                self.decide_all_archives()
                time.sleep(interval)
        poll = threading.Thread(target=go)
        poll.daemon = True
        poll.start()
        return event

    # TODO cleanup db of objects deleted in all clients
    # def cleanup(self):
    #     db = self.get_db()
    #     master_deleted = set(db.list_files_with_info(MASTER, {}))
    #     client_deleted = set(db.list_files_with_info(SLAVE, {}))
    #     deleted = master_deleted.intersection(client_deleted)


def conf(instance, auth_url, auth_token, container, local_root_path):
    settings = SyncerSettings(instance=instance,
                              auth_url=auth_url,
                              auth_token=auth_token,
                              container=container,
                              local_root_path=local_root_path)
    master = PithosFileClient(settings)
    slave = LocalfsFileClient(settings)
    return FileSyncer(settings, master, slave)
