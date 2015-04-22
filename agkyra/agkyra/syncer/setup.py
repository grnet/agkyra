import os
import threading
import logging

from agkyra.syncer.utils import join_path
from agkyra.syncer.database import SqliteFileStateDB
from agkyra.syncer.heartbeat import HeartBeat
from agkyra.syncer.messaging import Messager

from kamaki.clients import ClientError

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

thread_local_data = threading.local()


class SyncerSettings():
    def __init__(self, instance, auth_url, auth_token, container,
                 local_root_path,
                 *args, **kwargs):
        self.auth_url = auth_url
        self.auth_token = auth_token
        self.container = container

        self.ignore_ssl = kwargs.get("ignore_ssl", False)
        if self.ignore_ssl:
            https.patch_ignore_ssl()
        self.endpoint = self._get_pithos_client(
            auth_url, auth_token, container)

        self.home_dir = os.path.expanduser('~')
        self.settings_path = join_path(self.home_dir, GLOBAL_SETTINGS_NAME)
        self.create_dir(self.settings_path)
        self.instance_path = join_path(self.settings_path, instance)
        self.create_dir(self.instance_path)

        self.dbname = kwargs.get("dbname", DEFAULT_DBNAME)
        self.full_dbname = join_path(self.instance_path, self.dbname)
        self.get_db(initialize=True)

        self.local_root_path = local_root_path
        self.create_dir(self.local_root_path)

        self.cache_name = kwargs.get("cache_path", DEFAULT_CACHE_NAME)
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

        self.heartbeat = HeartBeat()
        self.action_max_wait = kwargs.get("action_max_wait",
                                          DEFAULT_ACTION_MAX_WAIT)
        self.messager = Messager()

    def get_db(self, initialize=False):
        dbs = getattr(thread_local_data, "dbs", None)
        if dbs is not None:
            db = dbs.get(self.full_dbname)
        else:
            db = None

        if db is None:
            logger.info("Connecting db: '%s', thread: %s" %
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
