import os
import re
import time
import datetime
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

from agkyra.syncer.file_client import FileClient
from agkyra.syncer import utils, common
from agkyra.syncer.database import transaction

logger = logging.getLogger(__name__)

LOCAL_FILE = 0
LOCAL_EMPTY_DIR = 1
LOCAL_NONEMPTY_DIR = 2
LOCAL_MISSING = 3
LOCAL_SOFTLINK = 4
LOCAL_OTHER = 5

OS_FILE_EXISTS = 17
OS_NOT_A_DIR = 20
OS_NO_FILE_OR_DIR = 2


class DirMissing(BaseException):
    pass


def link_file(src, dest):
    try:
        os.link(src, dest)
    except OSError as e:
        if e.errno in [OS_FILE_EXISTS, OS_NOT_A_DIR]:
            raise common.ConflictError("Cannot link, '%s' exists." % dest)
        if e.errno == OS_NO_FILE_OR_DIR:
            raise DirMissing()


def make_dirs(path):
    try:
        os.makedirs(path)
    except OSError as e:
        if e.errno == OS_FILE_EXISTS and os.path.isdir(path):
            return
        if e.errno in [OS_FILE_EXISTS, OS_NOT_A_DIR]:
            raise common.ConflictError("Cannot make dir '%s'." % path)
        raise


psutil_open_files = \
    (lambda proc: proc.open_files()) if psutil.version_info[0] >= 2 else \
    (lambda proc: proc.get_open_files())


def file_is_open(path):
    for proc in psutil.process_iter():
        try:
            flist = psutil_open_files(proc)
            for nt in flist:
                if nt.path == path:
                    return True
        except psutil.Error:
            pass
    return False


def mk_stash_name(filename):
    tstamp = datetime.datetime.now().strftime("%s")
    return filename + '.' + tstamp + '.local'


def eq_float(f1, f2):
    return abs(f1 - f2) < 0.01


def files_equal(f1, f2):
    logger.info("Comparing files: '%s', '%s'" % (f1, f2))
    st1 = path_status(f1)
    st2 = path_status(f2)
    if st1 != st2:
        return False
    if st1 != LOCAL_FILE:
        return True
    (mtime1, msize1) = stat_file(f1)
    (mtime2, msize2) = stat_file(f2)
    if msize1 != msize2:
        return False
    hash1 = utils.hash_file(f1)
    hash2 = utils.hash_file(f2)
    return hash1 == hash2


def info_is_unhandled(info):
    return info != {} and info[LOCALFS_TYPE] == common.T_UNHANDLED


def local_path_changes(path, state):
    live_info = get_live_info(path)
    info = state.info
    if is_info_eq(live_info, info):
        return None
    return live_info


def get_live_info(path):
    if path is None:
        return {}
    status = path_status(path)
    if status == LOCAL_MISSING:
        return {}
    if status in [LOCAL_SOFTLINK, LOCAL_OTHER]:
        return {LOCALFS_TYPE: common.T_UNHANDLED}
    if status in [LOCAL_EMPTY_DIR, LOCAL_NONEMPTY_DIR]:
        return {LOCALFS_TYPE: common.T_DIR}
    stats = stat_file(path)
    if stats is None:
        return {}
    (st_mtime, st_size) = stats
    live_info = {LOCALFS_MTIME: st_mtime,
                 LOCALFS_SIZE: st_size,
                 LOCALFS_TYPE: common.T_FILE,
                 }
    return live_info


def stat_file(filename):
    try:
        file_stats = os.lstat(filename)
    except OSError as e:
        if e.errno == OS_NO_FILE_OR_DIR:
            return None
        raise
    return (file_stats.st_mtime, file_stats.st_size)


LOCALFS_TYPE = "localfs_type"
LOCALFS_MTIME = "localfs_mtime"
LOCALFS_SIZE = "localfs_size"


def status_of_info(info):
    if info == {}:
        return LOCAL_MISSING
    if info[LOCALFS_TYPE] == common.T_DIR:
        return LOCAL_EMPTY_DIR
    if info[LOCALFS_TYPE] == common.T_UNHANDLED:
        return LOCAL_OTHER  # shouldn't happen
    return LOCAL_FILE


def path_status(path):
    if os.path.islink(path):
        return LOCAL_SOFTLINK
    try:
        contents = os.listdir(path)
        return LOCAL_NONEMPTY_DIR if contents else LOCAL_EMPTY_DIR
    except OSError as e:
        if e.errno == OS_NOT_A_DIR:
            if os.path.isfile(path):
                return LOCAL_FILE
            else:
                return LOCAL_OTHER
        if e.errno == OS_NO_FILE_OR_DIR:
            return LOCAL_MISSING


def old_path_status(path):
    try:
        contents = os.listdir(path)
        return LOCAL_NONEMPTY_DIR if contents else LOCAL_EMPTY_DIR
    except OSError as e:
        if e.errno == OS_NOT_A_DIR:
            return LOCAL_FILE
        if e.errno == OS_NO_FILE_OR_DIR:
            return LOCAL_MISSING


def is_info_eq(info1, info2):
    if {} in [info1, info2]:
        return info1 == info2
    if info1[LOCALFS_TYPE] != info2[LOCALFS_TYPE]:
        return False
    if info1[LOCALFS_TYPE] == common.T_UNHANDLED:
        return False
    if info1[LOCALFS_TYPE] == common.T_DIR:
        return True
    return eq_float(info1[LOCALFS_MTIME], info2[LOCALFS_MTIME]) \
        and info1[LOCALFS_SIZE] == info2[LOCALFS_SIZE]


class LocalfsTargetHandle(object):
    def __init__(self, settings, target_state):
        self.NAME = "LocalfsTargetHandle"
        self.rootpath = settings.local_root_path
        self.cache_hide_name = settings.cache_hide_name
        self.cache_hide_path = settings.cache_hide_path
        self.cache_path = settings.cache_path
        self.get_db = settings.get_db
        self.target_state = target_state
        self.objname = target_state.objname
        self.local_path = utils.join_path(self.rootpath, self.objname)
        self.hidden_filename = None
        self.hidden_path = None

    def get_path_in_cache(self, name):
        return utils.join_path(self.cache_path, name)

    @transaction()
    def register_hidden_name(self, filename):
        db = self.get_db()
        f = utils.hash_string(filename)
        hide_filename = utils.join_path(self.cache_hide_name, f)
        self.hidden_filename = hide_filename
        if db.get_cachename(hide_filename):
            return False
        db.insert_cachename(hide_filename, self.NAME, filename)
        return True

    @transaction()
    def unregister_hidden_name(self, hidden_filename):
        db = self.get_db()
        db.delete_cachename(hidden_filename)
        self.hidden_filename = None

    def hide_file(self):
        local_filename = self.local_path
        if file_is_open(local_filename):
            raise common.BusyError("File '%s' is open. Aborting."
                                   % local_filename)

        new_registered = self.register_hidden_name(self.objname)
        hidden_filename = self.hidden_filename
        hidden_path = self.get_path_in_cache(hidden_filename)
        self.hidden_path = hidden_path

        if not new_registered:
            logger.warning("Hiding already registered for file %s" %
                           (self.objname,))
            if os.path.lexists(hidden_path):
                logger.warning("File %s already hidden at %s" %
                               (self.objname, hidden_path))
                return
        try:
            os.rename(local_filename, hidden_path)
            logger.info("Hiding file '%s' to '%s'" %
                        (local_filename, hidden_path))
        except OSError as e:
            if e.errno == OS_NO_FILE_OR_DIR:
                self.unregister_hidden_name(hidden_filename)
                logger.info("File '%s' does not exist" % local_filename)
                return
            else:
                raise e
        if file_is_open(hidden_path):
            os.rename(hidden_path, local_filename)
            self.unregister_hidden_name(hidden_filename)
            raise common.BusyError("File '%s' is open. Undoing." % hidden_path)
        if path_status(hidden_path) == LOCAL_NONEMPTY_DIR:
            os.rename(hidden_path, local_filename)
            self.unregister_hidden_name(hidden_filename)
            raise common.ConflictError("'%s' is non-empty" % local_filename)

    def apply(self, fetched_file, fetched_live_info, sync_state):
        local_status = path_status(self.local_path)
        fetched_status = status_of_info(fetched_live_info)
        if local_status in [LOCAL_EMPTY_DIR, LOCAL_NONEMPTY_DIR] \
                and fetched_status == LOCAL_EMPTY_DIR:
            return
        if local_status == LOCAL_MISSING and fetched_status == LOCAL_MISSING:
            return
        if local_status == LOCAL_NONEMPTY_DIR:
            raise common.ConflictError("'%s' is non-empty" % self.local_path)

        self.prepare(fetched_file, sync_state)
        self.finalize(fetched_file, fetched_live_info)
        self.cleanup(self.hidden_path)
        self.unregister_hidden_name(self.hidden_filename)

    def prepare(self, fetched_file, sync_state):
        self.hide_file()
        info_changed = local_path_changes(self.hidden_path, sync_state)
        print 'info changed', info_changed
        if info_changed is not None and info_changed != {}:
            if not files_equal(self.hidden_path, fetched_file):
                self.stash_file()

    def stash_file(self):
        stash_name = mk_stash_name(self.objname)
        stash_path = utils.join_path(self.rootpath, stash_name)
        logger.warning("Stashing file '%s' to '%s'" %
                       (self.objname, stash_name))
        os.rename(self.hidden_path, stash_path)

    def finalize(self, filename, live_info):
        logger.info("Finalizing file '%s'" % filename)
        if live_info == {}:
            return
        if live_info[LOCALFS_TYPE] != common.T_DIR:
            try:
                link_file(filename, self.local_path)
            except DirMissing:
                make_dirs(os.path.dirname(self.local_path))
                link_file(filename, self.local_path)
        else:
            # assuming empty dir
            make_dirs(self.local_path)

    def cleanup(self, filename):
        status = path_status(filename)
        if status == LOCAL_FILE:
            try:
                logger.info("Cleaning up file '%s'" % filename)
                os.unlink(filename)
            except:
                pass
        elif status in [LOCAL_EMPTY_DIR, LOCAL_NONEMPTY_DIR]:
            os.rmdir(filename)

    def pull(self, source_handle, sync_state):
        fetched_file = source_handle.send_file(sync_state)
        fetched_live_info = get_live_info(fetched_file)
        self.apply(fetched_file, fetched_live_info, sync_state)
        self.cleanup(fetched_file)
        return self.target_state.set(info=fetched_live_info)


class LocalfsSourceHandle(object):
    @transaction()
    def register_stage_name(self, filename):
        db = self.get_db()
        f = utils.hash_string(filename)
        stage_filename = utils.join_path(self.cache_stage_name, f)
        self.stage_filename = stage_filename
        if db.get_cachename(stage_filename):
            return False
        db.insert_cachename(stage_filename, self.NAME, filename)
        return True

    @transaction()
    def unregister_stage_name(self, stage_filename):
        db = self.get_db()
        db.delete_cachename(stage_filename)
        self.stage_filename = None

    def get_path_in_cache(self, name):
        return utils.join_path(self.cache_path, name)

    def lock_file(self, local_filename):
        if file_is_open(local_filename):
            raise common.BusyError("File '%s' is open. Aborting"
                                   % local_filename)
        new_registered = self.register_stage_name(local_filename)
        stage_filename = self.stage_filename
        stage_path = self.get_path_in_cache(stage_filename)
        self.staged_path = stage_path

        if not new_registered:
            logger.warning("Staging already registered for file %s" %
                           (self.objname,))
            if os.path.lexists(stage_path):
                logger.warning("File %s already staged at %s" %
                               (self.objname, stage_path))
                return
        try:
            os.rename(local_filename, stage_path)
        except OSError as e:
            if e.errno == OS_NO_FILE_OR_DIR:
                logger.info("Source does not exist: '%s'" % local_filename)
                self.unregister_stage_name(stage_filename)
            else:
                raise e
        if file_is_open(stage_path):
            os.rename(stage_path, local_filename)
            self.unregister_stage_name(stage_filename)
            raise common.BusyError("File '%s' is open. Undoing" % stage_path)
        if path_status(stage_path) in [LOCAL_NONEMPTY_DIR, LOCAL_EMPTY_DIR]:
            os.rename(stage_path, local_filename)
            self.unregister_hidden_name(stage_filename)
            raise common.ConflictError("'%s' is non-empty" % local_filename)
        logger.info("Staging file '%s' to '%s'" % (self.objname, stage_path))

    def check_stable(self, interval=1, times=5):
        for i in range(times):
            live_info = local_path_changes(self.staged_file, self.source_state)
            if live_info is not None:
                return False
            time.sleep(interval)
        return True

    def __init__(self, settings, source_state):
        self.NAME = "LocalfsSourceHandle"
        self.rootpath = settings.local_root_path
        self.cache_stage_name = settings.cache_stage_name
        self.cache_stage_path = settings.cache_stage_path
        self.cache_path = settings.cache_path
        self.get_db = settings.get_db
        self.source_state = source_state
        self.objname = source_state.objname
        local_filename = utils.join_path(self.rootpath, self.objname)
        self.local_path = local_filename
        self.isdir = self.info_is_dir()
        self.stage_filename = None
        self.staged_path = None
        self.heartbeat = settings.heartbeat
        self.check_log()
        if not self.isdir:
            self.lock_file(local_filename)
            # self.check_stable()

    def check_log(self):
        with self.heartbeat.lock() as hb:
            prev_log = hb.get(self.objname)
            if prev_log is not None:
                actionstate, ts = prev_log
                if actionstate != self.NAME or \
                        utils.younger_than(ts, 10):
                    raise common.HandledError(
                        "Action mismatch in %s: %s %s" %
                        (self.NAME, self.objname, prev_log))
                logger.warning("Ignoring previous run in %s: %s %s" %
                               (self.NAME, self.objname, prev_log))
            hb.set(self.objname, (self.NAME, utils.time_stamp()))

    def get_synced_state(self):
        return self.source_state

    def info_is_dir(self):
        try:
            return self.source_state.info[LOCALFS_TYPE] == common.T_DIR
        except KeyError:
            return False

    def info_is_deleted(self):
        return self.source_state.info == {}

    def info_is_deleted_or_unhandled(self):
        return self.source_state.info == {} \
            or self.source_state.info[LOCALFS_TYPE] == common.T_UNHANDLED

    def stash_staged_file(self):
        stash_filename = mk_stash_name(self.local_path)
        logger.warning("Stashing file '%s' to '%s'" %
                       (self.local_path, stash_filename))
        os.rename(self.staged_path, stash_filename)

    def unstage_file(self):
        self.do_unstage()
        self.unregister_stage_name(self.stage_filename)
        self.clear_log()

    def clear_log(self):
        with self.heartbeat.lock() as hb:
            hb.delete(self.objname)

    def do_unstage(self):
        if self.stage_filename is None:
            return
        if self.info_is_deleted():
            return
        staged_path = self.staged_path
        try:
            link_file(staged_path, self.local_path)
            print "Unlinking", staged_path
            os.unlink(staged_path)
        except common.ConflictError:
            self.stash_staged_file()


class LocalfsFileClient(FileClient):
    def __init__(self, settings):
        self.settings = settings
        self.NAME = "LocalfsFileClient"
        self.ROOTPATH = settings.local_root_path
        self.CACHEPATH = settings.cache_path
        self.get_db = settings.get_db
        self.exclude_files_exp = re.compile('.*\.tmp$')
        self.exclude_dir_exp = re.compile(self.CACHEPATH)

    def list_candidate_files(self):
        db = self.get_db()
        candidates = {}
        for dirpath, dirnames, files in os.walk(self.ROOTPATH):
            rel_dirpath = os.path.relpath(dirpath, start=self.ROOTPATH)
            logger.debug("'%s' '%s'" % (dirpath, rel_dirpath))
            # if self.exclude_dir_exp.match(dirpath):
            #     continue
            if rel_dirpath != '.':
                candidates[rel_dirpath] = None
            for filename in files:
                # if self.exclude_files_exp.match(filename) or \
                #         self.exclude_dir_exp.match(filename):
                #     continue
                local_filename = utils.join_path(rel_dirpath, filename)
                candidates[local_filename] = None

        db_cands = dict((name, None) for name in db.list_files(self.NAME))
        candidates.update(db_cands)
        logger.info("Candidates: %s" % candidates)
        return candidates

    def _local_path_changes(self, name, state):
        local_path = utils.join_path(self.ROOTPATH, name)
        return local_path_changes(local_path, state)

    def start_probing_file(self, objname, old_state, ref_state,
                           assumed_info=None,
                           callback=None):
        if old_state.serial != ref_state.serial:
            logger.warning("Serial mismatch in probing path '%s'" % objname)
            return
        live_info = (self._local_path_changes(objname, old_state)
                     if assumed_info is None else assumed_info)
        if live_info is None:
            return
        live_state = old_state.set(info=live_info)
        if callback is not None:
            callback(live_state)

    def stage_file(self, source_state):
        return LocalfsSourceHandle(self.settings, source_state)

    def prepare_target(self, target_state):
        return LocalfsTargetHandle(self.settings, target_state)

    def notifier(self, callback=None):
        def handle_path(path):
            rel_path = os.path.relpath(path, start=self.ROOTPATH)
            if callback is not None:
                callback(self.NAME, rel_path)

        class EventHandler(FileSystemEventHandler):
            def on_created(this, event):
                # if not event.is_directory:
                #     return
                path = event.src_path
                if path.startswith(self.CACHEPATH):
                    return
                logger.info("Handling %s" % event)
                handle_path(path)

            def on_deleted(this, event):
                path = event.src_path
                if path.startswith(self.CACHEPATH):
                    return
                logger.info("Handling %s" % event)
                handle_path(path)

            def on_modified(this, event):
                if event.is_directory:
                    return
                path = event.src_path
                if path.startswith(self.CACHEPATH):
                    return
                logger.info("Handling %s" % event)
                handle_path(path)

            def on_moved(this, event):
                src_path = event.src_path
                dest_path = event.dest_path
                if src_path.startswith(self.CACHEPATH) or \
                        dest_path.startswith(self.CACHEPATH):
                    return
                logger.info("Handling %s" % event)
                handle_path(src_path)
                handle_path(dest_path)

        path = self.ROOTPATH
        event_handler = EventHandler()
        observer = Observer()
        observer.schedule(event_handler, path, recursive=True)
        observer.start()
        return observer
