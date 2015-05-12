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

import os
import stat
import re
import datetime
import psutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import logging

from agkyra.syncer.file_client import FileClient
from agkyra.syncer import utils, common, messaging
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


exclude_regexes = ["\.#", "\.~", "~\$", "~.*\.tmp$", "\..*\.swp$"]
exclude_pattern = re.compile('|'.join(exclude_regexes))


class DirMissing(BaseException):
    pass


def link_file(src, dest):
    try:
        os.link(src, dest)
    except OSError as e:
        if e.errno == OS_FILE_EXISTS:
            raise common.ConflictError("Cannot link, '%s' exists." % dest)
        if e.errno == OS_NOT_A_DIR:
            raise common.ConflictError(
                "Cannot link, missing path for '%s'." % dest)
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
    logger.debug("Comparing files: '%s', '%s'" % (f1, f2))
    stats1, st1 = get_local_status(f1)
    stats2, st2 = get_local_status(f2)
    if st1 != st2:
        return False
    if st1 != LOCAL_FILE:
        return True
    if stats1[stat.ST_SIZE] != stats2[stat.ST_SIZE]:
        return False
    hash1 = utils.hash_file(f1)
    hash2 = utils.hash_file(f2)
    return hash1 == hash2


def info_is_unhandled(info):
    return info != {} and info[LOCALFS_TYPE] == common.T_UNHANDLED


def local_path_changes(path, state, unhandled_equal=True):
    live_info = get_live_info(path)
    info = state.info
    if is_info_eq(live_info, info, unhandled_equal):
        return None
    return live_info


def get_live_info(path):
    if path is None:
        return {}
    stats, status = get_local_status(path)
    if status == LOCAL_MISSING:
        return {}
    if status in [LOCAL_SOFTLINK, LOCAL_OTHER]:
        return {LOCALFS_TYPE: common.T_UNHANDLED}
    if status in [LOCAL_EMPTY_DIR, LOCAL_NONEMPTY_DIR]:
        return {LOCALFS_TYPE: common.T_DIR}
    live_info = {LOCALFS_MTIME: stats[stat.ST_MTIME],
                 LOCALFS_SIZE: stats[stat.ST_SIZE],
                 LOCALFS_TYPE: common.T_FILE,
                 }
    return live_info


def stat_file(path):
    try:
        return os.lstat(path)
    except OSError as e:
        if e.errno in [OS_NO_FILE_OR_DIR, OS_NOT_A_DIR]:
            return None
        raise


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


def get_local_status(path, attempt=0):
    stats = stat_file(path)
    try:
        status = _get_local_status_from_stats(stats, path)
    except OSError as e:
        logger.warning("Got error '%s' while listing dir '%s'" % (e, path))
        if attempt > 2:
            raise
        return get_local_status(path, attempt + 1)
    return stats, status


def _get_local_status_from_stats(stats, path):
    if stats is None:
        return LOCAL_MISSING
    mode = stats[stat.ST_MODE]
    if stat.S_ISLNK(mode):
        return LOCAL_SOFTLINK
    if stat.S_ISREG(mode):
        return LOCAL_FILE
    if stat.S_ISDIR(mode):
        if os.listdir(path):
            return LOCAL_NONEMPTY_DIR
        return LOCAL_EMPTY_DIR
    return LOCAL_OTHER


def path_status(path):
    stats, status = get_local_status(path)
    return status


def is_info_eq(info1, info2, unhandled_equal=True):
    if {} in [info1, info2]:
        return info1 == info2
    if info1[LOCALFS_TYPE] != info2[LOCALFS_TYPE]:
        return False
    if info1[LOCALFS_TYPE] == common.T_UNHANDLED:
        return unhandled_equal
    if info1[LOCALFS_TYPE] == common.T_DIR:
        return True
    return eq_float(info1[LOCALFS_MTIME], info2[LOCALFS_MTIME]) \
        and info1[LOCALFS_SIZE] == info2[LOCALFS_SIZE]


class LocalfsTargetHandle(object):
    def __init__(self, settings, target_state):
        self.settings = settings
        self.SIGNATURE = "LocalfsTargetHandle"
        self.rootpath = settings.local_root_path
        self.cache_hide_name = settings.cache_hide_name
        self.cache_hide_path = settings.cache_hide_path
        self.cache_path = settings.cache_path
        self.get_db = settings.get_db
        self.target_state = target_state
        self.objname = target_state.objname
        self.fspath = utils.join_path(self.rootpath, self.objname)
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
        self.hidden_path = self.get_path_in_cache(self.hidden_filename)
        if db.get_cachename(hide_filename):
            return False
        db.insert_cachename(hide_filename, self.SIGNATURE, filename)
        return True

    @transaction()
    def unregister_hidden_name(self, hidden_filename):
        db = self.get_db()
        db.delete_cachename(hidden_filename)
        self.hidden_filename = None
        self.hidden_path = None

    def move_file(self):
        fspath = self.fspath
        if file_is_open(fspath):
            raise common.BusyError("File '%s' is open. Aborting."
                                   % fspath)

        new_registered = self.register_hidden_name(self.objname)
        hidden_filename = self.hidden_filename
        hidden_path = self.hidden_path

        if not new_registered:
            logger.warning("Hiding already registered for file %s" %
                           (self.objname,))
            if os.path.lexists(hidden_path):
                logger.warning("File %s already hidden at %s" %
                               (self.objname, hidden_path))
                return
        try:
            os.rename(fspath, hidden_path)
            logger.info("Hiding file '%s' to '%s'" %
                        (fspath, hidden_path))
        except OSError as e:
            if e.errno in [OS_NO_FILE_OR_DIR, OS_NOT_A_DIR]:
                self.unregister_hidden_name(hidden_filename)
                logger.info("File '%s' does not exist" % fspath)
                return
            else:
                raise e

    def hide_file(self):
        self.move_file()
        if self.hidden_filename is not None:
            if file_is_open(self.hidden_path):
                os.rename(self.hidden_path, self.fspath)
                self.unregister_hidden_name(self.hidden_filename)
                raise common.BusyError("File '%s' is open. Undoing." %
                                       self.hidden_path)
            if path_status(self.hidden_path) == LOCAL_NONEMPTY_DIR:
                os.rename(self.hidden_path, self.fspath)
                self.unregister_hidden_name(self.hidden_filename)
                raise common.ConflictError("'%s' is non-empty" % self.fspath)

    def apply(self, fetched_file, fetched_live_info, sync_state):
        local_status = path_status(self.fspath)
        fetched_status = status_of_info(fetched_live_info)
        if local_status in [LOCAL_EMPTY_DIR, LOCAL_NONEMPTY_DIR] \
                and fetched_status == LOCAL_EMPTY_DIR:
            return
        if local_status == LOCAL_MISSING and fetched_status == LOCAL_MISSING:
            return
        if local_status == LOCAL_NONEMPTY_DIR:
            raise common.ConflictError("'%s' is non-empty" % self.fspath)

        self.prepare(fetched_file, sync_state)
        self.finalize(fetched_file, fetched_live_info)
        self.cleanup(self.hidden_path)
        self.unregister_hidden_name(self.hidden_filename)

    def prepare(self, fetched_file, sync_state):
        self.hide_file()
        info_changed = local_path_changes(
            self.hidden_path, sync_state, unhandled_equal=False)
        if info_changed is not None and info_changed != {}:
            if not files_equal(self.hidden_path, fetched_file):
                self.stash_file()

    def stash_file(self):
        stash_name = mk_stash_name(self.objname)
        stash_path = utils.join_path(self.rootpath, stash_name)
        msg = messaging.ConflictStashMessage(
            objname=self.objname, stash_name=stash_name, logger=logger)
        self.settings.messager.put(msg)
        os.rename(self.hidden_path, stash_path)

    def finalize(self, filename, live_info):
        logger.info("Finalizing file '%s'" % filename)
        if live_info == {}:
            return
        if live_info[LOCALFS_TYPE] == common.T_FILE:
            try:
                link_file(filename, self.fspath)
            except DirMissing:
                make_dirs(os.path.dirname(self.fspath))
                link_file(filename, self.fspath)
        elif live_info[LOCALFS_TYPE] == common.T_DIR:
            make_dirs(self.fspath)
        else:
            raise AssertionError("info for fetched file '%s' is %s" %
                                 (filename, live_info))

    def cleanup(self, filename):
        if filename is None:
            return
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
        stage_path = self.get_path_in_cache(stage_filename)
        self.staged_path = stage_path
        if db.get_cachename(stage_filename):
            return False
        db.insert_cachename(stage_filename, self.SIGNATURE, filename)
        return True

    @transaction()
    def unregister_stage_name(self, stage_filename):
        db = self.get_db()
        db.delete_cachename(stage_filename)
        self.stage_filename = None
        self.staged_path = None

    def get_path_in_cache(self, name):
        return utils.join_path(self.cache_path, name)

    def lock_file(self):
        fspath = self.fspath
        if file_is_open(fspath):
            raise common.BusyError("File '%s' is open. Aborting"
                                   % fspath)
        new_registered = self.register_stage_name(fspath)
        stage_filename = self.stage_filename
        stage_path = self.staged_path

        if not new_registered:
            logger.warning("Staging already registered for file %s" %
                           (self.objname,))
            if os.path.lexists(stage_path):
                logger.warning("File %s already staged at %s" %
                               (self.objname, stage_path))
                return

        logger.info("Staging file '%s' to '%s'" % (self.objname, stage_path))
        try:
            os.rename(fspath, stage_path)
        except OSError as e:
            if e.errno in [OS_NO_FILE_OR_DIR, OS_NOT_A_DIR]:
                logger.info("Source does not exist: '%s'" % fspath)
                self.unregister_stage_name(stage_filename)
                return
            else:
                raise e

    def stage_file(self):
        self.lock_file()
        if self.staged_path is not None:
            if file_is_open(self.staged_path):
                os.rename(self.staged_path, self.fspath)
                self.unregister_stage_name(self.stage_filename)
                logger.warning("File '%s' is open; unstaged" % self.objname)
                raise common.BusyError("File '%s' is open. Undoing" %
                                       self.staged_path)

            if path_status(self.staged_path) != LOCAL_FILE:
                os.rename(self.staged_path, self.fspath)
                self.unregister_stage_name(self.stage_filename)
                logger.warning("Object '%s' is not a regular file; unstaged" %
                               self.objname)
        self.check_update_source_state()

    def __init__(self, settings, source_state):
        self.settings = settings
        self.SIGNATURE = "LocalfsSourceHandle"
        self.rootpath = settings.local_root_path
        self.cache_stage_name = settings.cache_stage_name
        self.cache_stage_path = settings.cache_stage_path
        self.cache_path = settings.cache_path
        self.get_db = settings.get_db
        self.source_state = source_state
        self.objname = source_state.objname
        self.fspath = utils.join_path(self.rootpath, self.objname)
        self.stage_filename = None
        self.staged_path = None
        self.heartbeat = settings.heartbeat
        if self.needs_staging():
            self.stage_file()

    @transaction()
    def update_state(self, state):
        db = self.get_db()
        db.put_state(state)

    def check_update_source_state(self):
        live_info = local_path_changes(
            self.staged_path, self.source_state)
        if live_info is not None:
            logger.warning("Actual info differs in %s for object: '%s'; "
                           "updating..." % (self.SIGNATURE, self.objname))
            new_state = self.source_state.set(info=live_info)
            self.update_state(new_state)
            self.source_state = new_state

    def get_synced_state(self):
        return self.source_state

    def needs_staging(self):
        info = self.source_state.info
        return info and info[LOCALFS_TYPE] == common.T_FILE

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
        stash_filename = mk_stash_name(self.fspath)
        logger.warning("Stashing file '%s' to '%s'" %
                       (self.fspath, stash_filename))
        os.rename(self.staged_path, stash_filename)

    def unstage_file(self):
        if self.stage_filename is None:
            return
        staged_path = self.staged_path
        try:
            link_file(staged_path, self.fspath)
            os.unlink(staged_path)
        except common.ConflictError:
            self.stash_staged_file()
        self.unregister_stage_name(self.stage_filename)


class LocalfsFileClient(FileClient):
    def __init__(self, settings):
        self.settings = settings
        self.SIGNATURE = "LocalfsFileClient"
        self.ROOTPATH = settings.local_root_path
        self.CACHEPATH = settings.cache_path
        self.get_db = settings.get_db
        self.probe_candidates = utils.ThreadSafeDict()

    def remove_candidates(self, objnames, ident):
        with self.probe_candidates.lock() as d:
            for objname in objnames:
                try:
                    cached = d.pop(objname)
                    if cached["ident"] != ident:
                        d[objname] = cached
                except KeyError:
                    pass

    def list_candidate_files(self, forced=False):
        with self.probe_candidates.lock() as d:
            if forced:
                candidates = self.walk_filesystem()
                d.update(candidates)
            return d.keys()

    def none_info(self):
        return {"ident": None, "info": None}

    def walk_filesystem(self):
        candidates = {}
        for dirpath, dirnames, files in os.walk(self.ROOTPATH):
            rel_dirpath = os.path.relpath(dirpath, start=self.ROOTPATH)
            logger.debug("'%s' '%s'" % (dirpath, rel_dirpath))
            if rel_dirpath != '.':
                objname = utils.to_standard_sep(rel_dirpath)
                candidates[objname] = self.none_info()
            for filename in files:
                if rel_dirpath == '.':
                    prefix = ""
                else:
                    prefix = utils.to_standard_sep(rel_dirpath)
                objname = utils.join_objname(prefix, filename)
                candidates[objname] = self.none_info()

        db_cands = dict((name, self.none_info())
                        for name in self.list_files())
        candidates.update(db_cands)
        logger.info("Candidates: %s" % candidates)
        return candidates

    @transaction()
    def list_files(self):
        db = self.get_db()
        return db.list_files(self.SIGNATURE)

    def _local_path_changes(self, name, state):
        local_path = utils.join_path(self.ROOTPATH, name)
        return local_path_changes(local_path, state)

    def exclude_file(self, objname):
        parts = objname.split(common.OBJECT_DIRSEP)
        init_part = parts[0]
        if init_part in [self.settings.cache_name]:
            return True
        final_part = parts[-1]
        return exclude_pattern.match(final_part)

    def probe_file(self, objname, old_state, ref_state, ident):
        with self.probe_candidates.lock() as d:
            try:
                cached = d[objname]
                cached_info = cached["info"]
                cached["ident"] = ident
            except KeyError:
                cached_info = None

        if self.exclude_file(objname):
            logger.warning("Ignoring probe archive: %s, object: %s" %
                           (old_state.archive, objname))
            return

        live_info = (self._local_path_changes(objname, old_state)
                     if cached_info is None else cached_info)
        if live_info is None:
            return
        live_state = old_state.set(info=live_info)
        return live_state

    def stage_file(self, source_state):
        return LocalfsSourceHandle(self.settings, source_state)

    def prepare_target(self, target_state):
        return LocalfsTargetHandle(self.settings, target_state)

    def notifier(self):
        def handle_path(path):
            rel_path = os.path.relpath(path, start=self.ROOTPATH)
            objname = utils.to_standard_sep(rel_path)
            with self.probe_candidates.lock() as d:
                d[objname] = self.none_info()

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
