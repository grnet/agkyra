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
import threading
import logging

from functools import wraps

from agkyra.syncer.utils import join_path, ThreadSafeDict
from agkyra.syncer.database import SqliteFileStateDB, transaction
from agkyra.syncer.messaging import Messager
from agkyra.syncer import utils

from kamaki.clients import ClientError, KamakiSSLError

from kamaki.clients.astakos import AstakosClient
from kamaki.clients.pithos import PithosClient
from kamaki.clients.utils import https

logger = logging.getLogger(__name__)


DEFAULT_CACHE_NAME = '.agkyra_cache'
DEFAULT_CACHE_HIDE_NAME = 'hidden'
DEFAULT_CACHE_STAGE_NAME = 'staged'
DEFAULT_CACHE_FETCH_NAME = 'fetched'
GLOBAL_SETTINGS_NAME = '.agkyra'
DEFAULT_DBNAME = "syncer.db"
DEFAULT_ACTION_MAX_WAIT = 10
DEFAULT_PITHOS_LIST_INTERVAL = 5
DEFAULT_CONNECTION_RETRY_LIMIT = 3
INSTANCES_NAME = 'instances'

thread_local_data = threading.local()


def get_instance(elems):
    data = "".join(elems)
    return utils.hash_string(data)


def ssl_fall_back(method):
    """Catch an SSL error while executing a method, patch kamaki and retry"""
    @wraps(method)
    def wrap(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except KamakiSSLError as ssle:
            logger.debug('Kamaki SSL failed %s' % ssle)
            logger.info(
                'Kamaki SSL failed, fall back to certifi (mozilla certs)')
            import certifi
            https.patch_with_certs(certifi.where())
            return method(self, *args, **kwargs)
    return wrap


def check_encoding():
    platform = utils.PLATFORM
    encoding = utils.ENCODING
    if platform.startswith("linux"):
        if not encoding.lower() in ['utf-8', 'utf8']:
            raise Exception(
                "Cannot operate with encoding %s. Please use UTF-8."
                % encoding)


class SyncerSettings():
    def __init__(self, auth_url, auth_token, container, local_root_path,
                 *args, **kwargs):
        check_encoding()
        auth_url = utils.to_unicode(auth_url)
        auth_token = utils.to_unicode(auth_token)
        container = utils.to_unicode(container)
        local_root_path = utils.to_unicode(local_root_path)
        self.auth_url = utils.normalize_standard_suffix(auth_url)
        self.auth_token = auth_token
        self.container = utils.normalize_standard_suffix(container)

        self.ignore_ssl = kwargs.get("ignore_ssl", False)
        if self.ignore_ssl:
            https.patch_ignore_ssl()
        elif kwargs.get('ca_certs', None):
            https.patch_with_certs(kwargs['ca_certs'])

        self.endpoint = self._get_pithos_client(
            auth_url, auth_token, container)

        container_exists = self.check_container_exists(container)

        home_dir = utils.to_unicode(os.path.expanduser('~'))
        default_settings_path = join_path(home_dir, GLOBAL_SETTINGS_NAME)
        self.settings_path = utils.to_unicode(
            kwargs.get("agkyra_path", default_settings_path))
        self.create_dir(self.settings_path)

        self.instances_path = join_path(self.settings_path, INSTANCES_NAME)
        self.create_dir(self.instances_path)

        self.local_root_path = utils.normalize_local_suffix(local_root_path)
        local_root_path_exists = os.path.isdir(self.local_root_path)

        self.cache_name = utils.to_unicode(
            kwargs.get("cache_name", DEFAULT_CACHE_NAME))
        self.cache_path = join_path(self.local_root_path, self.cache_name)

        self.cache_hide_name = utils.to_unicode(
            kwargs.get("cache_hide_name", DEFAULT_CACHE_HIDE_NAME))
        self.cache_hide_path = join_path(self.cache_path, self.cache_hide_name)

        self.cache_stage_name = utils.to_unicode(
            kwargs.get("cache_stage_name", DEFAULT_CACHE_STAGE_NAME))
        self.cache_stage_path = join_path(self.cache_path,
                                          self.cache_stage_name)

        self.cache_fetch_name = utils.to_unicode(
            kwargs.get("cache_fetch_name", DEFAULT_CACHE_FETCH_NAME))
        self.cache_fetch_path = join_path(self.cache_path,
                                          self.cache_fetch_name)

        self.user_id = self.endpoint.account
        self.instance = get_instance(
            [self.auth_url, self.user_id,
             self.container, self.local_root_path])
        self.instance_path = join_path(self.instances_path, self.instance)
        self.create_dir(self.instance_path)

        self.dbname = utils.to_unicode(kwargs.get("dbname", DEFAULT_DBNAME))
        self.full_dbname = join_path(self.instance_path, self.dbname)

        db_existed = os.path.isfile(self.full_dbname)
        if not db_existed:
            self.get_db(initialize=True)

        if not db_existed:
            self.set_localfs_enabled(True)
            self.create_local_dirs()
            self.set_pithos_enabled(True)
            if not container_exists:
                self.mk_container(container)
        else:
            if not local_root_path_exists:
                self.set_localfs_enabled(False)
            if not container_exists:
                self.set_pithos_enabled(False)

        self.heartbeat = ThreadSafeDict()
        self.action_max_wait = kwargs.get("action_max_wait",
                                          DEFAULT_ACTION_MAX_WAIT)
        self.pithos_list_interval = kwargs.get("pithos_list_interval",
                                               DEFAULT_PITHOS_LIST_INTERVAL)

        self.connection_retry_limit = kwargs.get(
            "connection_retry_limit", DEFAULT_CONNECTION_RETRY_LIMIT)
        self.endpoint.CONNECTION_RETRY_LIMIT = self.connection_retry_limit

        self.messager = Messager()
        self.mtime_lag = 0 #self.determine_mtime_lag()

    def create_local_dirs(self):
        self.create_dir(self.local_root_path)
        self.create_dir(self.cache_path)
        self.create_dir(self.cache_hide_path)
        self.create_dir(self.cache_stage_path)
        self.create_dir(self.cache_fetch_path)

    def determine_mtime_lag(self):
        st = os.stat(self.cache_path)
        mtime = st.st_mtime
        if mtime.is_integer():
            return 1.1
        return 0

    def get_db(self, initialize=False):
        dbs = getattr(thread_local_data, "dbs", None)
        if dbs is not None:
            db = dbs.get(self.full_dbname)
        else:
            db = None

        if db is None:
            logger.debug("Connecting db: '%s', thread: %s" %
                         (self.full_dbname, threading.current_thread().ident))
            db = SqliteFileStateDB(self.full_dbname, initialize=initialize)
            if dbs is None:
                thread_local_data.dbs = {}
            thread_local_data.dbs[self.full_dbname] = db
        return db

    def create_dir(self, path):
        if os.path.exists(path):
            if os.path.isdir(path):
                return
            raise Exception("Cannot create dir '%s'; file exists" % path)
        logger.warning("Creating dir: '%s'" % path)
        os.mkdir(path)
        return path

    @ssl_fall_back
    def _get_pithos_client(self, auth_url, token, container):
        try:
            astakos = AstakosClient(auth_url, token)
        except ClientError:
            logger.error("Failed to authenticate user token")
            raise
        try:
            PITHOS_URL = astakos.get_endpoint_url(PithosClient.service_type)
        except ClientError:
            logger.error("Failed to get endpoints for Pithos")
            raise
        try:
            account = astakos.user_info['id']
            return PithosClient(PITHOS_URL, token, account, container)
        except ClientError:
            logger.error("Failed to initialize Pithos client")
            raise

    def check_container_exists(self, container):
        try:
            self.endpoint.get_container_info(container)
            return True
        except ClientError as e:
            if e.status == 404:
                return False
            else:
                raise

    def mk_container(self, container):
        try:
            self.endpoint.create_container(container)
            logger.warning("Creating container '%s'" % container)
        except ClientError:
            logger.error("Failed to create container '%s'" % container)
            raise

    @transaction()
    def set_localfs_enabled(self, enabled):
        db = self.get_db()
        self._set_localfs_enabled(db, enabled)

    def _set_localfs_enabled(self, db, enabled):
        db.set_config("localfs_enabled", enabled)

    @transaction()
    def set_pithos_enabled(self, enabled):
        db = self.get_db()
        self._set_pithos_enabled(db, enabled)

    def _set_pithos_enabled(self, db, enabled):
        db.set_config("pithos_enabled", enabled)

    @transaction()
    def localfs_is_enabled(self):
        db = self.get_db()
        return self._localfs_is_enabled(db)

    def _localfs_is_enabled(self, db):
        return db.get_config("localfs_enabled")

    @transaction()
    def pithos_is_enabled(self):
        db = self.get_db()
        return self._pithos_is_enabled(db)

    def _pithos_is_enabled(self, db):
        return db.get_config("pithos_enabled")

    def _sync_is_enabled(self, db):
        return self._localfs_is_enabled(db) and self._pithos_is_enabled(db)

    @transaction()
    def purge_db_archives_and_enable(self):
        db = self.get_db()
        db.purge_archives()
        if not self._localfs_is_enabled(db):
            self.create_local_dirs()
            self._set_localfs_enabled(db, True)
        if not self._pithos_is_enabled(db):
            self._set_pithos_enabled(db, True)
            self.mk_container(self.container)
