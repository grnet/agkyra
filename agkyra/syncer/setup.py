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
from agkyra.syncer.database import SqliteFileStateDB
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


class SyncerSettings():
    def __init__(self, auth_url, auth_token, container, local_root_path,
                 *args, **kwargs):
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

        home_dir = os.path.expanduser('~')
        default_settings_path = join_path(home_dir, GLOBAL_SETTINGS_NAME)
        self.settings_path = kwargs.get("agkyra_path", default_settings_path)
        self.create_dir(self.settings_path)

        self.instances_path = join_path(self.settings_path, INSTANCES_NAME)
        self.create_dir(self.instances_path)

        self.local_root_path = utils.normalize_local_suffix(local_root_path)
        self.create_dir(self.local_root_path)

        self.user_id = self.endpoint.account
        self.instance = get_instance(
            [self.auth_url, self.user_id,
             self.container, self.local_root_path])
        self.instance_path = join_path(self.instances_path, self.instance)
        self.create_dir(self.instance_path)

        self.dbname = kwargs.get("dbname", DEFAULT_DBNAME)
        self.full_dbname = join_path(self.instance_path, self.dbname)
        self.get_db(initialize=True)

        self.cache_name = kwargs.get("cache_name", DEFAULT_CACHE_NAME)
        self.cache_path = join_path(self.local_root_path, self.cache_name)
        self.create_dir(self.cache_path)

        self.cache_hide_name = kwargs.get("cache_hide_name",
                                          DEFAULT_CACHE_HIDE_NAME)
        self.cache_hide_path = join_path(self.cache_path, self.cache_hide_name)
        self.create_dir(self.cache_hide_path)

        self.cache_stage_name = kwargs.get("cache_stage_name",
                                           DEFAULT_CACHE_STAGE_NAME)
        self.cache_stage_path = join_path(self.cache_path,
                                          self.cache_stage_name)
        self.create_dir(self.cache_stage_path)

        self.cache_fetch_name = kwargs.get("cache_fetch_name",
                                           DEFAULT_CACHE_FETCH_NAME)
        self.cache_fetch_path = join_path(self.cache_path,
                                          self.cache_fetch_name)
        self.create_dir(self.cache_fetch_path)

        self.heartbeat = ThreadSafeDict()
        self.action_max_wait = kwargs.get("action_max_wait",
                                          DEFAULT_ACTION_MAX_WAIT)
        self.pithos_list_interval = kwargs.get("pithos_list_interval",
                                               DEFAULT_PITHOS_LIST_INTERVAL)

        self.connection_retry_limit = kwargs.get(
            "connection_retry_limit", DEFAULT_CONNECTION_RETRY_LIMIT)
        self.endpoint.CONNECTION_RETRY_LIMIT = self.connection_retry_limit

        self.messager = Messager()

        self.mtime_lag = self.determine_mtime_lag()

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
            client = PithosClient(PITHOS_URL, token, account, container)
        except ClientError:
            logger.error("Failed to initialize Pithos client")
            raise
        try:
            client.get_container_info(container)
        except ClientError as e:
            if e.status == 404:
                logger.warning(
                    "Container '%s' does not exist, creating..." % container)
                try:
                    client.create_container(container)
                except ClientError:
                    logger.error("Failed to create container '%s'" % container)
                    raise
            else:
                raise

        return client
