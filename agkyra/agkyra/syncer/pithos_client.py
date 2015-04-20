from functools import wraps
import time
import os
import datetime
import threading
import random
import logging
import re

from agkyra.syncer import utils, common
from agkyra.syncer.file_client import FileClient
from agkyra.syncer.setup import ClientError
from agkyra.syncer.database import transaction

logger = logging.getLogger(__name__)


def heartbeat_event(settings, heartbeat, path):
    event = threading.Event()
    max_interval = settings.action_max_wait / 2.0

    def set_log():
        with heartbeat.lock() as hb:
            client, prev_tstamp = hb.get(path)
            tpl = (client, utils.time_stamp())
            hb.set(path, tpl)
            logger.info("HEARTBEAT %s %s %s" % ((path,) + tpl))

    def go():
        interval = 0.2
        while True:
            if event.is_set():
                break
            set_log()
            time.sleep(interval)
            interval = min(2 * interval, max_interval)
    thread = threading.Thread(target=go)
    thread.start()
    return event


def give_heartbeat(f):
    @wraps(f)
    def inner(*args, **kwargs):
        obj = args[0]
        path = obj.path
        heartbeat = obj.heartbeat
        settings = obj.settings
        event = heartbeat_event(settings, heartbeat, path)
        try:
            return f(*args, **kwargs)
        finally:
            event.set()
    return inner


class PithosSourceHandle(object):
    def __init__(self, settings, source_state):
        self.NAME = "PithosSourceHandle"
        self.settings = settings
        self.endpoint = settings.endpoint
        self.cache_fetch_name = settings.cache_fetch_name
        self.cache_fetch_path = settings.cache_fetch_path
        self.cache_path = settings.cache_path
        self.get_db = settings.get_db
        self.source_state = source_state
        self.path = source_state.path
        self.heartbeat = settings.heartbeat
        self.check_log()

    def check_log(self):
        with self.heartbeat.lock() as hb:
            prev_log = hb.get(self.path)
            if prev_log is not None:
                actionstate, ts = prev_log
                if actionstate != self.NAME or \
                        utils.younger_than(ts, self.settings.action_max_wait):
                    raise common.HandledError("Action mismatch in %s: %s %s" %
                                              (self.NAME, self.path, prev_log))
                logger.warning("Ignoring previous run in %s: %s %s" %
                               (self.NAME, self.path, prev_log))
            hb.set(self.path, (self.NAME, utils.time_stamp()))

    @transaction()
    def register_fetch_name(self, filename):
        db = self.get_db()
        f = utils.hash_string(filename) + "_" + \
            datetime.datetime.now().strftime("%s")
        fetch_name = utils.join_path(self.cache_fetch_name, f)
        self.fetch_name = fetch_name
        db.insert_cachepath(fetch_name, self.NAME, filename)
        return utils.join_path(self.cache_path, fetch_name)

    @give_heartbeat
    def send_file(self, sync_state):
        fetched_file = self.register_fetch_name(self.path)
        headers = dict()
        with open(fetched_file, mode='wb+') as fil:
            try:
                logger.info("Downloading path: '%s', to: '%s'" %
                            (self.path, fetched_file))
                self.endpoint.download_object(
                    self.path,
                    fil,
                    headers=headers)
            except ClientError as e:
                if e.status == 404:
                    actual_info = {}
                else:
                    raise e
            else:
                actual_etag = headers["x-object-hash"]
                actual_type = (common.T_DIR if object_isdir(headers)
                               else common.T_FILE)
                actual_info = {"pithos_etag": actual_etag,
                               "pithos_type": actual_type}
            self.source_state = self.source_state.set(info=actual_info)
        if actual_info == {}:
            logger.info("Downloading path: '%s', object is gone." % self.path)
            os.unlink(fetched_file)
        elif actual_info["pithos_type"] == common.T_DIR:
            logger.info("Downloading path: '%s', object is dir." % self.path)
            os.unlink(fetched_file)
            os.mkdir(fetched_file)
        return fetched_file

    def get_synced_state(self):
        return self.source_state

    def unstage_file(self):
        self.clear_log()

    def clear_log(self):
        with self.heartbeat.lock() as hb:
            hb.delete(self.path)


STAGED_FOR_DELETION_SUFFIX = ".pithos_staged_for_deletion"
exclude_staged_regex = ".*" + STAGED_FOR_DELETION_SUFFIX + "$"
exclude_pattern = re.compile(exclude_staged_regex)


class PithosTargetHandle(object):
    def __init__(self, settings, target_state):
        self.settings = settings
        self.endpoint = settings.endpoint
        self.target_state = target_state
        self.target_file = target_state.path
        self.path = target_state.path
        self.heartbeat = settings.heartbeat

    def mk_del_name(self, name):
        tstamp = datetime.datetime.now().strftime("%s")
        rand = str(random.getrandbits(64))
        return "%s.%s.%s%s" % (name, tstamp, rand, STAGED_FOR_DELETION_SUFFIX)

    def safe_object_del(self, path, etag):
        container = self.endpoint.container
        del_name = self.mk_del_name(path)
        try:
            self.endpoint.object_move(
                path,
                destination='/%s/%s' % (container, del_name),
                if_etag_match=etag)
        except ClientError as e:
            logger.warning("'%s' not found; already deleted?" % path)
            if e.status == 404:
                return
        self.endpoint.del_object(del_name)

    def directory_put(self, path, etag):
        r = self.endpoint.object_put(
            path,
            content_type='application/directory',
            content_length=0,
            if_etag_match=etag)
        return r

    @give_heartbeat
    def pull(self, source_handle, sync_state):
#        assert isinstance(source_handle, LocalfsSourceHandle)
        info = sync_state.info
        etag = info.get("pithos_etag")
        if source_handle.info_is_deleted_or_unhandled():
            if etag is not None:
                logger.info("Deleting object '%s'" % self.target_file)
                self.safe_object_del(self.target_file, etag)
            live_info = {}
        elif source_handle.info_is_dir():
            logger.info("Creating dir '%s'" % source_handle.path)
            r = self.directory_put(source_handle.path, etag)
            synced_etag = r.headers["etag"]
            live_info = {"pithos_etag": synced_etag,
                         "pithos_type": common.T_DIR}
        else:
            with open(source_handle.staged_path, mode="rb") as fil:
                r = self.endpoint.upload_object(
                    self.target_file,
                    fil,
                    if_etag_match=info.get("pithos_etag"))
                synced_etag = r["etag"]
                live_info = {"pithos_etag": synced_etag,
                             "pithos_type": common.T_FILE}
        return self.target_state.set(info=live_info)


def object_isdir(obj):
    try:
        content_type = obj["content_type"]
    except KeyError:
        content_type = obj["content-type"]
    return any(txt in content_type for txt in ['application/directory',
                                               'application/folder'])


PITHOS_TYPE = "pithos_type"
PITHOS_ETAG = "pithos_etag"


class PithosFileClient(FileClient):
    def __init__(self, settings):
        self.settings = settings
        self.NAME = "PithosFileClient"
        self.auth_url = settings.auth_url
        self.auth_token = settings.auth_token
        self.container = settings.container
        self.get_db = settings.get_db
        self.endpoint = settings.endpoint

    def list_candidate_files(self, last_modified=None):
        db = self.get_db()
        objects = self.endpoint.list_objects()
        self.objects = objects
        upstream_all_names = set(obj["name"] for obj in objects)
        non_deleted_in_db = set(db.list_non_deleted_files(self.NAME))
        newly_deleted = non_deleted_in_db.difference(upstream_all_names)
        logger.debug("newly_deleted %s" % newly_deleted)
        if last_modified is not None:
            upstream_modified_names = set(
                obj["name"] for obj in objects
                if obj["last_modified"] > last_modified)
            upstream_names = upstream_modified_names
        else:
            upstream_names = upstream_all_names
        candidates = upstream_names.union(newly_deleted)
        logger.info("Candidates: %s" % candidates)
        return candidates

    def notifier(self, callback=None, interval=10):
        class PollPithos(threading.Thread):
            def run(this):
                while True:
                    utcnow = datetime.datetime.utcnow()
                    last_tstamp = (utcnow -
                                   datetime.timedelta(seconds=interval))
                    last_modified = last_tstamp.isoformat()
                    candidates = self.list_candidate_files(
                        last_modified=last_modified)
                    if callback is not None:
                        for candidate in candidates:
                            callback(self.NAME, candidate)
                    time.sleep(interval)

        poll = PollPithos()
        poll.daemon = True
        poll.start()

    def get_object_from_cache(self, path):
        if self.objects is None:
            self.objects = self.endpoint.list_objects()
        objs = [o for o in self.objects if o["name"] == path]
        try:
            return objs[0]
        except IndexError:
            return None

    def get_object(self, path):
        try:
            return self.endpoint.get_object_info(path)
        except ClientError as e:
            if e.status == 404:
                return None
            raise e

    def get_object_live_info(self, obj):
        if obj is None:
            return {}
        p_type = common.T_DIR if object_isdir(obj) else common.T_FILE
        obj_hash = obj["x-object-hash"]
        return {PITHOS_ETAG: obj_hash,
                PITHOS_TYPE: p_type,
                }

    def start_probing_path(self, path, old_state, ref_state, callback=None):
        if exclude_pattern.match(path):
            logger.warning("Ignoring probe archive: %s, path: '%s'" %
                           (old_state.archive, path))
            return
        info = old_state.info
        obj = self.get_object(path)
        live_info = self.get_object_live_info(obj)
        if info != live_info:
            if callback is not None:
                live_state = old_state.set(info=live_info)
                callback(live_state)

    def stage_file(self, source_state):
        return PithosSourceHandle(self.settings, source_state)

    def prepare_target(self, target_state):
        return PithosTargetHandle(self.settings, target_state)
