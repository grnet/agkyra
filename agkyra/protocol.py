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

from wsgiref.simple_server import make_server
from ws4py.websocket import WebSocket
from ws4py.server.wsgiutils import WebSocketWSGIApplication
from ws4py.server.wsgirefserver import WSGIServer, WebSocketWSGIRequestHandler
from hashlib import sha1
from threading import Thread
import time
import os
import sys
import json
import logging
import subprocess
from agkyra.syncer import (
    syncer, setup, pithos_client, localfs_client, messaging, utils, database,
    common)
from agkyra.config import AgkyraConfig, AGKYRA_DIR

if getattr(sys, 'frozen', False):
    # we are running in a |PyInstaller| bundle
    BASEDIR = sys._MEIPASS
    ISFROZEN = True
else:
    # we are running in a normal Python environment
    BASEDIR = os.path.dirname(os.path.realpath(__file__))
    ISFROZEN = False

RESOURCES = os.path.join(BASEDIR, 'resources')

LOGGER = logging.getLogger(__name__)
SYNCERS = utils.ThreadSafeDict()

with open(os.path.join(RESOURCES, 'ui_data/common_en.json')) as f:
    COMMON = json.load(f)
STATUS = COMMON['STATUS']


class SessionDB(database.DB):
    def init(self):
        db = self.db
        db.execute(
            'CREATE TABLE IF NOT EXISTS heart ('
            'ui_id VARCHAR(256), address text, beat VARCHAR(32)'
            ')')

    def get_all_heartbeats(self):
        db = self.db
        r = db.execute('SELECT * FROM heart')
        return r.fetchall()

    def register_heartbeat(self, ui_id, address):
        db = self.db
        db.execute('INSERT INTO heart VALUES (?, ?, ?)',
                   (ui_id, address, time.time()))

    def update_heartbeat(self, ui_id):
        db = self.db
        r = db.execute('SELECT ui_id FROM heart WHERE ui_id=?', (ui_id,))
        if r.fetchall():
            db.execute('UPDATE heart SET beat=? WHERE ui_id=?',
                       (time.time(), ui_id))
            return True
        return False

    def unregister_heartbeat(self, ui_id):
        db = self.db
        db.execute('DELETE FROM heart WHERE ui_id=?', (ui_id,))


class SessionHelper(object):
    """Enables creation of a session daemon and retrieves credentials of an
    existing one
    """
    session_timeout = 20

    def __init__(self, **kwargs):
        """Setup the helper server"""
        db_name = kwargs.get(
            'session_db', os.path.join(AGKYRA_DIR, 'session.db'))
        self.session_db = common.DBTuple(dbtype=SessionDB, dbname=db_name)
        database.initialize(self.session_db)

    def load_active_session(self):
        with database.TransactedConnection(self.session_db) as db:
            return self._load_active_session(db)

    def _load_active_session(self, db):
        """Load a session from db"""
        sessions = db.get_all_heartbeats()
        if sessions:
            last, expected_id = sessions[-1], getattr(self, 'ui_id', None)
            if expected_id and last[0] != '%s' % expected_id:
                LOGGER.debug('Session ID is old')
                return None
            now, last_beat = time.time(), float(last[2])
            if now - last_beat < self.session_timeout:
                # Found an active session
                return dict(ui_id=last[0], address=last[1])
        LOGGER.debug('No active sessions found')
        return None

    def create_session_daemon(self):
        """Create and return a new daemon, or None if one exists"""
        with database.TransactedConnection(self.session_db) as db:
            session = self._load_active_session(db)
            if session:
                return None
            session_daemon = SessionDaemon(self.session_db)
            db.register_heartbeat(session_daemon.ui_id, session_daemon.address)
            return session_daemon

    def wait_session_to_load(self, timeout=20, step=0.2):
        """Wait while the session is loading e.g. in another process
            :returns: the session or None if timeout
        """
        time_passed = 0
        while time_passed < timeout:
            self.session = self.load_active_session()
            if self.session:
                return self.session
            time_passed += step
            time.sleep(step)
        return None

    def wait_session_to_stop(self, timeout=20, step=2):
        """Wait while the session is shutting down
            :returns: True if stopped, False if timed out and still running
        """
        time_passed = 0
        while time_passed < timeout and self.load_active_session():
            time.sleep(step)
            time_passed += step
        return not bool(self.load_active_session())


class SessionDaemon(object):
    """A WebSocket server which inspects a heartbeat and decides whether to
    shut down
    """
    def __init__(self, session_db, *args, **kwargs):
        self.session_db = session_db
        ui_id = sha1(os.urandom(128)).hexdigest()

        LOCAL_ADDR = '127.0.0.1'
        WebSocketProtocol.ui_id = ui_id
        WebSocketProtocol.session_db = session_db
        server = make_server(
            LOCAL_ADDR, 0,
            server_class=WSGIServer,
            handler_class=WebSocketWSGIRequestHandler,
            app=WebSocketWSGIApplication(handler_cls=WebSocketProtocol))
        server.initialize_websockets_manager()
        address = 'ws://%s:%s' % (LOCAL_ADDR, server.server_port)
        self.server = server
        self.ui_id = ui_id
        self.address = address

    def heartbeat(self):
        """Periodically update the session database timestamp"""
        while True:
            time.sleep(2)
            with database.TransactedConnection(self.session_db) as db:
                found = db.update_heartbeat(self.ui_id)
                if not found:
                    break
        self.close_manager()
        self.server.shutdown()

    def close_manager(self):
        manager = self.server.manager
        manager.close_all()
        manager.stop()
        manager.join()

    def start(self):
        """Start the server in a thread"""
        t = Thread(target=self.heartbeat)
        t.start()
        self.server.serve_forever()
        t.join()
        LOGGER.debug('WSGI server is down')


class WebSocketProtocol(WebSocket):
    """Helper-side WebSocket protocol for communication with GUI:

    -- INTERNAL HANDSAKE --
    GUI: {"method": "post", "ui_id": <GUI ID>}
    HELPER: {"ACCEPTED": 202, "action": "post ui_id"}" or
        "{"REJECTED": 401, "action": "post ui_id"}

    -- ERRORS WITH SIGNIFICANCE --
    -- SHUT DOWN --
    GUI: {"method": "post", "path": "shutdown"}

    -- PAUSE --
    GUI: {"method": "post", "path": "pause"}
    HELPER: {"OK": 200, "action": "post pause"} or error

    -- START --
    GUI: {"method": "post", "path": "start"}
    HELPER: {"OK": 200, "action": "post start"} or error

    -- FORCE START --
    GUI: {"method": "post", "path": "force"}
    HELPER: {"OK": 200, "action": "post force"} or error

    -- GET SETTINGS --
    GUI: {"method": "get", "path": "settings"}
    HELPER:
        {
            "action": "get settings",
            "token": <user token>,
            "url": <auth url>,
            "container": <container>,
            "directory": <local directory>,
            "exclude": <file path>,
            "language": <en|el>,
            "ask_to_sync": <true|false>
        } or {<ERROR>: <ERROR CODE>}

    -- PUT SETTINGS --
    GUI: {
            "method": "put", "path": "settings",
            "token": <user token>,
            "url": <auth url>,
            "container": <container>,
            "directory": <local directory>,
            "exclude": <file path>,
            "language": <en|el>,
            "ask_to_sync": <true|false>
        }
    HELPER: {"CREATED": 201, "action": "put settings",} or
        {<ERROR>: <ERROR CODE>, "action": "get settings",}

    -- GET STATUS --
    GUI: {"method": "get", "path": "status"}
    HELPER: {"code": <int>,
            "synced": <int>, "unsynced": <int>, "failed": <int>,
            "action": "get status"
        } or {<ERROR>: <ERROR CODE>, "action": "get status"}
    """
    status = utils.ThreadSafeDict()
    with status.lock() as d:
        d.update(code=STATUS['UNINITIALIZED'], synced=0, unsynced=0, failed=0)

    ui_id = None
    session_db = None
    accepted = False
    settings = dict(
        token=None, url=None,
        container=None, directory=None,
        exclude=None, ask_to_sync=True, language="en")
    cnf = AgkyraConfig()
    essentials = ('url', 'token', 'container', 'directory')

    def get_status(self, key=None):
        """:return: updated status dict or value of specified key"""
        if self.syncer and self.can_sync():
            self._consume_messages()
            with self.status.lock() as d:
                LOGGER.debug('Status was %s' % d['code'])
                if d['code'] in (
                        STATUS['UNINITIALIZED'], STATUS['INITIALIZING']):
                    if self.syncer.paused:
                        d['code'] = STATUS['PAUSED']
                    elif d['code'] != STATUS['PAUSING'] or (
                            d['unsynced'] == d['synced'] + d['failed']):
                        d['code'] = STATUS['SYNCING']
        with self.status.lock() as d:
            LOGGER.debug('Status is now %s' % d['code'])
            return d.get(key, None) if key else dict(d)

    def set_status(self, **kwargs):
        with self.status.lock() as d:
            LOGGER.debug('Set status to %s' % kwargs)
            d.update(kwargs)

    @property
    def syncer(self):
        """:returns: the first syncer object or None"""
        with SYNCERS.lock() as d:
            for sync_key, sync_obj in d.items():
                return sync_obj
        return None

    def clean_db(self):
        """Clean DB from current session trace"""
        LOGGER.debug('Remove current session trace')
        with database.TransactedConnection(self.session_db) as db:
            db.unregister_heartbeat(self.ui_id)

    def shutdown_syncer(self, syncer_key=0, timeout=None):
        """Shutdown the syncer backend object"""
        LOGGER.debug('Shutdown syncer')
        with SYNCERS.lock() as d:
            syncer = d.pop(syncer_key, None)
            if syncer and self.can_sync():
                remaining = syncer.stop_all_daemons(timeout=timeout)
                LOGGER.debug('Wait open syncs to complete')
                syncer.wait_sync_threads(timeout=remaining)

    def _get_default_sync(self):
        """Get global.default_sync or pick the first sync as default
        If there are no syncs, create a 'default' sync.
        """
        sync = self.cnf.get('global', 'default_sync')
        if not sync:
            for sync in self.cnf.keys('sync'):
                break
            self.cnf.set('global', 'default_sync', sync or 'default')
        return sync or 'default'

    def _get_sync_cloud(self, sync):
        """Get the <sync>.cloud or pick the first cloud and use it
        In case of cloud picking, set the cloud as the <sync>.cloud for future
        sessions.
        If no clouds are found, create a 'default' cloud, with an empty url.
        """
        try:
            cloud = self.cnf.get_sync(sync, 'cloud')
        except KeyError:
            cloud = None
        if not cloud:
            for cloud in self.cnf.keys('cloud'):
                break
            self.cnf.set_sync(sync, 'cloud', cloud or 'default')
        return cloud or 'default'

    def _load_settings(self):
        LOGGER.debug('Start loading settings')
        sync = self._get_default_sync()
        cloud = self._get_sync_cloud(sync)

        for option in ('url', 'token'):
            try:
                value = self.cnf.get_cloud(cloud, option)
                if not value:
                    raise Exception()
                self.settings[option] = value
            except Exception:
                self.settings[option] = None
                self.set_status(code=STATUS['SETTINGS MISSING'])

        self.settings['ask_to_sync'] = (
            self.cnf.get('global', 'ask_to_sync') == 'on')
        self.settings['language'] = self.cnf.get('global', 'language')

        # for option in ('container', 'directory', 'exclude'):
        for option in ('container', 'directory'):
            try:
                 value = self.cnf.get_sync(sync, option)
                 if not value:
                    raise KeyError()
                 self.settings[option] = value
            except KeyError:
                LOGGER.debug('No %s is set' % option)
                self.set_status(code=STATUS['SETTINGS MISSING'])

        LOGGER.debug('Finished loading settings')

    def _dump_settings(self):
        LOGGER.debug('Saving settings')
        sync = self._get_default_sync()

        cloud = self._get_sync_cloud(sync)
        new_url = self.settings.get('url') or ''
        new_token = self.settings.get('token') or ''

        try:
            old_url = self.cnf.get_cloud(cloud, 'url') or ''
        except KeyError:
            old_url = new_url

        while old_url and old_url != new_url:
            cloud = '%s_%s' % (cloud, sync)
            try:
                self.cnf.get_cloud(cloud, 'url')
            except KeyError:
                break

        LOGGER.debug('Cloud name is %s' % cloud)
        self.cnf.set_cloud(cloud, 'url', new_url)
        self.cnf.set_cloud(cloud, 'token', new_token)
        self.cnf.set_sync(sync, 'cloud', cloud)

        LOGGER.debug('Save sync settings, name is %s' % sync)
        # for option in ('directory', 'container', 'exclude'):
        for option in ('directory', 'container'):
            self.cnf.set_sync(sync, option, self.settings.get(option) or '')

        self.cnf.set('global', 'language', self.settings.get('language', 'en'))
        ask_to_sync = self.settings.get('ask_to_sync', True)
        self.cnf.set('global', 'ask_to_sync', 'on' if ask_to_sync else 'off')

        self.cnf.write()
        LOGGER.debug('Settings saved')

    def _essentials_changed(self, new_settings):
        """Check if essential settings have changed in new_settings"""
        return any([
            self.settings[e] != new_settings[e] for e in self.essentials])

    def _consume_messages(self, max_consumption=10):
        """Update status by consuming and understanding syncer messages"""
        if self.can_sync():
            msg = self.syncer.get_next_message()
            # if not msg:
            #     with self.status.lock() as d:
            #         if d['unsynced'] == d['synced'] + d['failed']:
            #             d.update(unsynced=0, synced=0, failed=0)
            while msg:
                if isinstance(msg, messaging.SyncMessage):
                    LOGGER.debug(
                        'UNSYNCED +1 %s' % getattr(msg, 'objname', ''))
                    self.set_status(unsynced=self.get_status('unsynced') + 1)
                elif isinstance(msg, messaging.AckSyncMessage):
                    LOGGER.debug('SYNCED +1 %s' % getattr(msg, 'objname', ''))
                    self.set_status(synced=self.get_status('synced') + 1)
                elif isinstance(msg, messaging.SyncErrorMessage):
                    LOGGER.debug('FAILED +1 %s' % getattr(msg, 'objname', ''))
                    self.set_status(failed=self.get_status('failed') + 1)
                elif isinstance(msg, messaging.LocalfsSyncDisabled):
                    LOGGER.debug(
                        'STOP BACKEND, %s'% getattr(msg, 'objname', ''))
                    LOGGER.debug(
                        'CHANGE STATUS TO: %s' % STATUS['DIRECTORY ERROR'])
                    self.set_status(code=STATUS['DIRECTORY ERROR'])
                    self.syncer.stop_all_daemons()
                elif isinstance(msg, messaging.PithosSyncDisabled):
                    LOGGER.debug(
                        'STOP BACKEND, %s'% getattr(msg, 'objname', ''))
                    self.set_status(code=STATUS['CONTAINER ERROR'])
                    self.syncer.stop_all_daemons()
                elif isinstance(msg, messaging.PithosAuthTokenError):
                    LOGGER.debug(
                        'STOP BACKEND, %s'% getattr(msg, 'objname', ''))
                    self.set_status(code=STATUS['TOKEN ERROR'])
                    self.syncer.stop_all_daemons()
                elif isinstance(msg, messaging.PithosGenericError):
                    LOGGER.debug(
                        'STOP BACKEND, %s'% getattr(msg, 'objname', ''))
                    self.set_status(code=STATUS['CRITICAL ERROR'])
                    self.syncer.stop_all_daemons()
                LOGGER.debug('Backend message: %s %s' % (msg.name, type(msg)))
                # Limit the amount of messages consumed each time
                max_consumption -= 1
                if max_consumption:
                    msg = self.syncer.get_next_message()
                else:
                    break

    def can_sync(self):
        """Check if settings are enough to setup a syncing proccess"""
        return all([self.settings[e] for e in self.essentials])

    def init_sync(self, leave_paused=False):
        """Initialize syncer"""
        self.set_status(code=STATUS['INITIALIZING'])
        sync = self._get_default_sync()

        kwargs = dict(agkyra_path=AGKYRA_DIR)
        # Get SSL settings
        cloud = self._get_sync_cloud(sync)
        try:
            ignore_ssl = self.cnf.get_cloud(cloud, 'ignore_ssl') in ('on', )
            kwargs['ignore_ssl'] = ignore_ssl
        except KeyError:
            ignore_ssl = None
        if not ignore_ssl:
            try:
                kwargs['ca_certs'] = self.cnf.get_cloud(cloud, 'ca_certs')
            except KeyError:
                pass

        syncer_ = None
        try:
            syncer_settings = setup.SyncerSettings(
                self.settings['url'], self.settings['token'],
                self.settings['container'], self.settings['directory'],
                **kwargs)
            master = pithos_client.PithosFileClient(syncer_settings)
            slave = localfs_client.LocalfsFileClient(syncer_settings)
            syncer_ = syncer.FileSyncer(syncer_settings, master, slave)
            # Check if syncer is ready, by consuming messages
            local_ok, remote_ok = False, False
            for i in range(2):

                LOGGER.debug('Get message %s' % (i + 1))
                msg = syncer_.get_next_message(block=True)
                LOGGER.debug('Got message: %s' % msg)

                if isinstance(msg, messaging.LocalfsSyncDisabled):
                    self.set_status(code=STATUS['DIRECTORY ERROR'])
                    local_ok = False
                    break
                elif isinstance(msg, messaging.PithosSyncDisabled):
                    self.set_status(code=STATUS['CONTAINER ERROR'])
                    remote_ok = False
                    break
                elif isinstance(msg, messaging.LocalfsSyncEnabled):
                    local_ok = True
                elif isinstance(msg, messaging.PithosSyncEnabled):
                    remote_ok = True
                else:
                    LOGGER.error('Unexpected message %s' % msg)
                    self.set_status(code=STATUS['CRITICAL ERROR'])
                    break
            if local_ok and remote_ok:
                syncer_.initiate_probe()
                new_status = 'PAUSED' if leave_paused else 'READY'
                self.set_status(code=STATUS[new_status])
        except pithos_client.ClientError as ce:
            LOGGER.debug('backend init failed: %s %s' % (ce, ce.status))
            try:
                code = {
                    400: STATUS['AUTH URL ERROR'],
                    401: STATUS['TOKEN ERROR'],
                }[ce.status]
            except KeyError:
                code = STATUS['UNINITIALIZED']
            self.set_status(code=code)
        finally:
            self.set_status(synced=0, unsynced=0)
            with SYNCERS.lock() as d:
                d[0] = syncer_

    # Syncer-related methods
    def get_settings(self):
        return self.settings

    def set_settings(self, new_settings):
        """Set the settings and dump them to permanent storage if needed"""
        # Prepare setting save
        old_status = self.get_status('code')
        ok_not_syncing = [STATUS['READY'], STATUS['PAUSING'], STATUS['PAUSED']]
        active = ok_not_syncing + [STATUS['SYNCING']]

        must_reset_syncing = self._essentials_changed(new_settings)
        if must_reset_syncing and old_status in active:
            LOGGER.debug('Temporary backend shutdown to save settings')
            self.shutdown_syncer()

        # save settings
        self.settings.update(new_settings)
        self._dump_settings()

        # Restart
        LOGGER.debug('Reload settings')
        self._load_settings()
        can_sync = must_reset_syncing and self.can_sync()
        if can_sync:
            leave_paused = old_status in ok_not_syncing
            LOGGER.debug('Restart backend')
            self.init_sync(leave_paused=leave_paused)

    def _pause_syncer(self):
        syncer_ = self.syncer
        syncer_.stop_decide()
        LOGGER.debug('Wait open syncs to complete')
        syncer_.wait_sync_threads()

    def pause_sync(self):
        """Pause syncing (assuming it is up and running)"""
        if self.syncer:
            self.set_status(code=STATUS['PAUSING'])
            self.syncer.stop_decide()
            self.set_status(code=STATUS['PAUSED'])

    def start_sync(self):
        """Start syncing"""
        self.syncer.start_decide()
        self.set_status(code=STATUS['SYNCING'])

    def force_sync(self):
        """Force syncing, assuming there is a directory or container problem"""
        self.set_status(code=STATUS['INITIALIZING'])
        self.syncer.settings.purge_db_archives_and_enable()
        self.syncer.initiate_probe()
        self.set_status(code=STATUS['READY'])

    def send_json(self, msg):
        LOGGER.debug('send: %s' % msg)
        self.send(json.dumps(msg))

    # Protocol handling methods
    def _post(self, r):
        """Handle POST requests"""
        if self.accepted:
            action = r['path']
            if action == 'shutdown':
                # Clean db to cause syncer backend to shut down
                self.set_status(code=STATUS['SHUTTING DOWN'])
                self.shutdown_syncer(timeout=5)
                self.clean_db()
                return
            {
                'init': self.init_sync,
                'start': self.start_sync,
                'pause': self.pause_sync,
                'force': self.force_sync
            }[action]()
            self.send_json({'OK': 200, 'action': 'post %s' % action})
        elif r['ui_id'] == self.ui_id:
            self.accepted = True
            self.send_json({'ACCEPTED': 202, 'action': 'post ui_id'})
            self._load_settings()
            status = self.get_status('code')
            if self.can_sync() and status == STATUS['UNINITIALIZED']:
                self.set_status(code=STATUS['SETTINGS READY'])
        else:
            action = r.get('path', 'ui_id')
            self.send_json({'REJECTED': 401, 'action': 'post %s' % action})
            self.terminate()

    def _put(self, r):
        """Handle PUT requests"""
        if self.accepted:
            LOGGER.debug('put %s' % r)
            action = r.pop('path')
            self.set_settings(r)
            r.update({'CREATED': 201, 'action': 'put %s' % action})
            self.send_json(r)
        else:
            action = r['path']
            self.send_json({
                'UNAUTHORIZED UI': 401, 'action': 'put %s' % action})
            self.terminate()

    def _get(self, r):
        """Handle GET requests"""
        action = r.pop('path')
        if not self.accepted:
            self.send_json({
                'UNAUTHORIZED UI': 401, 'action': 'get %s' % action})
            self.terminate()
        else:
            data = {
                'settings': self.get_settings,
                'status': self.get_status,
            }[action]()
            data['action'] = 'get %s' % action
            self.send_json(data)

    def received_message(self, message):
        """Route requests to corresponding handling methods"""
        try:
            r = json.loads('%s' % message)
        except ValueError as ve:
            self.send_json({'BAD REQUEST': 400})
            LOGGER.error('JSON ERROR: %s' % ve)
            return
        try:
            method = r.pop('method')
            {
                'post': self._post,
                'put': self._put,
                'get': self._get
            }[method](r)
        except KeyError as ke:
            action = method + ' ' + r.get('path', '')
            self.send_json({'BAD REQUEST': 400, 'action': action})
            LOGGER.error('KEY ERROR: %s' % ke)
        except setup.ClientError as ce:
            action = '%s %s' % (
                method, r.get('path', 'ui_id' if 'ui_id' in r else ''))
            self.send_json({'%s' % ce: ce.status, 'action': action})
            return
        except Exception as e:
            self.send_json({'INTERNAL ERROR': 500})
            reason = '%s %s' % (method or '', r)
            LOGGER.error('EXCEPTION (%s): %s' % (reason, e))
            self.terminate()


def close_fds():
    import resource
    # Default maximum for the number of available file descriptors.
    MAXFD = 1024

    maxfd = resource.getrlimit(resource.RLIMIT_NOFILE)[1]
    if (maxfd == resource.RLIM_INFINITY):
        maxfd = MAXFD

    # Iterate through and close all file descriptors.
    for fd in range(2, maxfd):
        try:
            os.close(fd)
        except OSError:  # ERROR, fd wasn't open to begin with (ignored)
            pass


# Adapted from https://code.activestate.com/recipes/278731/
def daemonize(command):
    # Default working directory for the daemon.
    WORKDIR = "/"

    # The standard I/O file descriptors are redirected to /dev/null by default.
    if (hasattr(os, "devnull")):
        REDIRECT_TO = os.devnull
    else:
        REDIRECT_TO = "/dev/null"

    pid = os.fork()
    if not pid:
        # To become the session leader of this new session and the process
        # group leader of the new process group, we call os.setsid(). The
        # process is also guaranteed not to have a controlling terminal.
        os.setsid()

        # Fork a second child and exit immediately to prevent zombies.
        pid = os.fork()
        if not pid:
            # Since the current working directory may be a mounted
            # filesystem, we avoid the issue of not being able to unmount
            # the filesystem at shutdown time by changing it to the root
            # directory.
            os.chdir(WORKDIR)

            # Close all open file descriptors. This prevents the child from
            # keeping open any file descriptors inherited from the parent.
            # There is a variety of methods to accomplish this task.
            close_fds()

            # Redirect the standard I/O file descriptors to the specified
            # file. Since the daemon has no controlling terminal, most
            # daemons redirect stdin, stdout, and stderr to /dev/null. This
            # is done to prevent side-effects from reads and writes to the
            # standard I/O file descriptors.

            # This call to open is guaranteed to return the lowest file
            # descriptor, which will be 0 (stdin), since it was closed
            # above.
            os.open(REDIRECT_TO, os.O_RDWR)  # standard input (0)

            # Duplicate standard input to standard output and standard error.
            os.dup2(0, 1)  # standard output (1)
            os.dup2(0, 2)  # standard error (2)

            os.execlp(*command)
        else:
            os._exit(0)
    else:
        os.wait()


def launch_server(callback, debug):
    """Launch the server in a separate process"""
    LOGGER.info('Start SessionHelper session')
    opts = ["start", "daemon"]
    if debug:
        opts.append('-d')
    if utils.iswin():
        command = [] if ISFROZEN else ["pythonw.exe"]
        command.append(callback)
        command += opts
        subprocess.Popen(command, close_fds=True)
    else:
        command = [callback, callback]
        command += opts
        daemonize(command)
