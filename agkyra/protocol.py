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
import sqlite3
import time
import os
import json
import logging
from agkyra.syncer import (
    syncer, setup, pithos_client, localfs_client, messaging, utils)
from agkyra.config import AgkyraConfig, AGKYRA_DIR


CURPATH = os.path.dirname(os.path.abspath(__file__))

LOG = logging.getLogger(__name__)
SYNCERS = utils.ThreadSafeDict()


def retry_on_locked_db(method, *args, **kwargs):
    """If DB is locked, wait and try again"""
    wait = kwargs.get('wait', 0.2)
    retries = kwargs.get('retries', 2)
    while retries:
        try:
            return method(*args, **kwargs)
        except sqlite3.OperationalError as oe:
            if 'locked' not in '%s' % oe:
                raise
            LOG.debug('%s, retry' % oe)
        time.sleep(wait)
        retries -= 1


class SessionHelper(object):
    """Agkyra Helper Server sets a WebSocket server with the Helper protocol
    It also provided methods for running and killing the Helper server
    """
    session_timeout = 20

    def __init__(self, **kwargs):
        """Setup the helper server"""
        self.session_db = kwargs.get(
            'session_db', os.path.join(AGKYRA_DIR, 'session.db'))
        self.session_relation = kwargs.get('session_relation', 'heart')

        LOG.debug('Connect to db')
        self.db = sqlite3.connect(self.session_db)

        self._init_db_relation()
        # self.session = self._load_active_session() or self._create_session()

        # self.db.close()

    def _init_db_relation(self):
        """Create the session relation"""
        self.db.execute('BEGIN')
        self.db.execute(
            'CREATE TABLE IF NOT EXISTS %s ('
            'ui_id VARCHAR(256), address text, beat VARCHAR(32)'
            ')' % self.session_relation)
        self.db.commit()

    def load_active_session(self):
        """Load a session from db"""
        r = self.db.execute('SELECT * FROM %s' % self.session_relation)
        sessions = r.fetchall()
        if sessions:
            last, expected_id = sessions[-1], getattr(self, 'ui_id', None)
            if expected_id and last[0] != '%s' % expected_id:
                LOG.debug('Session ID is old')
                return None
            now, last_beat = time.time(), float(last[2])
            if now - last_beat < self.session_timeout:
                # Found an active session
                return dict(ui_id=last[0], address=last[1])
        LOG.debug('No active sessions found')
        return None

    def create_session(self):
        """Return the active session or create a new one"""

        def get_session():
                self.db.execute('BEGIN')
                return self.load_active_session()

        session = retry_on_locked_db(get_session)
        if session:
            self.db.rollback()
            return session

        ui_id = sha1(os.urandom(128)).hexdigest()

        LOCAL_ADDR = '127.0.0.1'
        WebSocketProtocol.ui_id = ui_id
        WebSocketProtocol.session_db = self.session_db
        WebSocketProtocol.session_relation = self.session_relation
        server = make_server(
            LOCAL_ADDR, 0,
            server_class=WSGIServer,
            handler_class=WebSocketWSGIRequestHandler,
            app=WebSocketWSGIApplication(handler_cls=WebSocketProtocol))
        server.initialize_websockets_manager()
        address = 'ws://%s:%s' % (LOCAL_ADDR, server.server_port)

        self.db.execute('INSERT INTO %s VALUES ("%s", "%s", "%s")' % (
            self.session_relation, ui_id, address, time.time()))
        self.db.commit()

        self.server = server
        self.ui_id = ui_id
        return dict(ui_id=ui_id, address=address)

    def wait_session_to_load(self, timeout=20, step=2):
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

    def heartbeat(self):
        """General session heartbeat - when heart stops, WSGI server dies"""
        db, alive = sqlite3.connect(self.session_db), True
        while alive:
            time.sleep(2)
            try:
                db.execute('BEGIN')
                r = db.execute('SELECT ui_id FROM %s WHERE ui_id="%s"' % (
                    self.session_relation, self.ui_id))
                if r.fetchall():
                    db.execute('UPDATE %s SET beat="%s" WHERE ui_id="%s"' % (
                        self.session_relation, time.time(), self.ui_id))
                else:
                    alive = False
                db.commit()
            except sqlite3.OperationalError as oe:
                if 'locked' not in '%s' % oe:
                    raise
        db.close()

    def start(self):
        """Start the helper server in a thread"""
        if getattr(self, 'server', None):
            t = Thread(target=self._shutdown_daemon)
            t.start()
            Thread(target=self.heartbeat).start()
            self.server.serve_forever()
            t.join()
            LOG.debug('WSGI server is down')

    def _shutdown_daemon(self):
        """Shutdown WSGI server when the heart stops"""
        db = sqlite3.connect(self.session_db)
        while True:
            time.sleep(4)
            try:
                r = db.execute('SELECT ui_id FROM %s WHERE ui_id="%s"' % (
                    self.session_relation, self.ui_id))
                if not r.fetchall():
                    db.close()
                    time.sleep(5)
                    t = Thread(target=self.server.shutdown)
                    t.start()
                    t.join()
                    break
            except sqlite3.OperationalError:
                pass


class WebSocketProtocol(WebSocket):
    """Helper-side WebSocket protocol for communication with GUI:

    -- INTERNAL HANDSAKE --
    GUI: {"method": "post", "ui_id": <GUI ID>}
    HELPER: {"ACCEPTED": 202, "action": "post ui_id"}" or
        "{"REJECTED": 401, "action": "post ui_id"}

    -- ERRORS WITH SIGNIFICANCE --
    If the token doesn't work:
    HELPER: {"action": <action that caused the error>, "UNAUTHORIZED": 401}

    -- SHUT DOWN --
    GUI: {"method": "post", "path": "shutdown"}

    -- PAUSE --
    GUI: {"method": "post", "path": "pause"}
    HELPER: {"OK": 200, "action": "post pause"} or error

    -- START --
    GUI: {"method": "post", "path": "start"}
    HELPER: {"OK": 200, "action": "post start"} or error

    -- GET SETTINGS --
    GUI: {"method": "get", "path": "settings"}
    HELPER:
        {
            "action": "get settings",
            "token": <user token>,
            "url": <auth url>,
            "container": <container>,
            "directory": <local directory>,
            "exclude": <file path>
        } or {<ERROR>: <ERROR CODE>}

    -- PUT SETTINGS --
    GUI: {
            "method": "put", "path": "settings",
            "token": <user token>,
            "url": <auth url>,
            "container": <container>,
            "directory": <local directory>,
            "exclude": <file path>
        }
    HELPER: {"CREATED": 201, "action": "put settings",} or
        {<ERROR>: <ERROR CODE>, "action": "get settings",}

    -- GET STATUS --
    GUI: {"method": "get", "path": "status"}
    HELPER: {
        "can_sync": <boolean>,
        "notification": <int>,
        "paused": <boolean>,
        "action": "get status"} or
        {<ERROR>: <ERROR CODE>, "action": "get status"}
    """
    notification = {
        0: 'Syncer is consistent',
        1: 'Local directory is not accessible',
        2: 'Remote container is not accessible',
        100: 'unknown error'
    }
    ui_id = None
    session_db, session_relation = None, None
    accepted = False
    settings = dict(
        token=None, url=None,
        container=None, directory=None,
        exclude=None)
    status = dict(
        notification=0, synced=0, unsynced=0, paused=True, can_sync=False)
    cnf = AgkyraConfig()
    essentials = ('url', 'token', 'container', 'directory')

    @property
    def syncer(self):
        with SYNCERS.lock() as d:
            for sync_key, sync_obj in d.items():
                return sync_obj
        return None

    def _shutdown(self):
        """Shutdown the service"""
        LOG.debug('Shutdown syncer')
        self.close()
        if self.syncer and self.can_sync():
            self.syncer.stop_all_daemons()
            LOG.debug('Wait open syncs to complete')
            self.syncer.wait_sync_threads()

    def clean_db(self):
        """Clean DB from session traces"""
        LOG.debug('Remove session traces')
        db = sqlite3.connect(self.session_db)
        db.execute('BEGIN')
        db.execute('DELETE FROM %s WHERE ui_id="%s"' % (
            self.session_relation, self.ui_id))
        db.commit()
        db.close()

    def heartbeat(self):
        """Check if socket should be alive"""
        db, alive = sqlite3.connect(self.session_db), True
        while alive:
            time.sleep(1)
            try:
                db.execute('BEGIN')
                r = db.execute('SELECT ui_id FROM %s WHERE ui_id="%s"' % (
                    self.session_relation, self.ui_id))
                if r.fetchall():
                    db.execute('UPDATE %s SET beat="%s" WHERE ui_id="%s"' % (
                        self.session_relation, time.time(), self.ui_id))
                else:
                    alive = False
                db.commit()
            except sqlite3.OperationalError:
                alive = True
        db.close()
        self._shutdown()

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
        LOG.debug('Start loading settings')
        sync = self._get_default_sync()
        cloud = self._get_sync_cloud(sync)

        try:
            self.settings['url'] = self.cnf.get_cloud(cloud, 'url')
        except Exception:
            self.settings['url'] = None
        try:
            self.settings['token'] = self.cnf.get_cloud(cloud, 'token')
        except Exception:
            self.settings['url'] = None

        # for option in ('container', 'directory', 'exclude'):
        for option in ('container', 'directory'):
            try:
                self.settings[option] = self.cnf.get_sync(sync, option)
            except KeyError:
                LOG.debug('No %s is set' % option)

        LOG.debug('Finished loading settings')

    def _dump_settings(self):
        LOG.debug('Saving settings')
        sync = self._get_default_sync()
        changes = False

        if not self.settings.get('url', None):
            LOG.debug('No cloud settings to save')
        else:
            LOG.debug('Save cloud settings')
            cloud = self._get_sync_cloud(sync)

            try:
                old_url = self.cnf.get_cloud(cloud, 'url') or ''
            except KeyError:
                old_url = self.settings['url']

            while old_url and old_url != self.settings['url']:
                cloud = '%s_%s' % (cloud, sync)
                try:
                    self.cnf.get_cloud(cloud, 'url')
                except KeyError:
                    break

            LOG.debug('Cloud name is %s' % cloud)
            self.cnf.set_cloud(cloud, 'url', self.settings['url'])
            self.cnf.set_cloud(cloud, 'token', self.settings['token'] or '')
            self.cnf.set_sync(sync, 'cloud', cloud)
            changes = True

        LOG.debug('Save sync settings, name is %s' % sync)
        # for option in ('directory', 'container', 'exclude'):
        for option in ('directory', 'container'):
            self.cnf.set_sync(sync, option, self.settings[option] or '')
            changes = True

        if changes:
            self.cnf.write()
            LOG.debug('Settings saved')
        else:
            LOG.debug('No setting changes spotted')

    def _essentials_changed(self, new_settings):
        """Check if essential settings have changed in new_settings"""
        return all([
            self.settings[e] == self.settings[e] for e in self.essentials])

    def _consume_messages(self):
        """Update status by consuming and understanding syncer messages"""
        if self.can_sync():
            msg = self.syncer.get_next_message()
            if not msg:
                if self.status['unsynced'] == self.status['synced']:
                    self.status['unsynced'] = 0
                    self.status['synced'] = 0
            while (msg):
                if isinstance(msg, messaging.SyncMessage):
                    # LOG.info('Start syncing "%s"' % msg.objname)
                    self.status['unsynced'] += 1
                elif isinstance(msg, messaging.AckSyncMessage):
                    # LOG.info('Finished syncing "%s"' % msg.objname)
                    self.status['synced'] += 1
                # elif isinstance(msg, messaging.CollisionMessage):
                #     LOG.info('Collision for "%s"' % msg.objname)
                # elif isinstance(msg, messaging.ConflictStashMessage):
                #     LOG.info('Conflict for "%s"' % msg.objname)
                if isinstance(msg, messaging.LocalfsSyncDisabled):
                    # LOG.debug('Local FS is dissabled, noooo!')
                    self.status['notification'] = 1
                    self.syncer.stop_all_daemons()
                elif isinstance(msg, messaging.PithosSyncDisabled):
                    # LOG.debug('Pithos sync is disabled, noooooo!')
                    self.status['notification'] = 2
                    self.syncer.stop_all_daemons()
                LOG.debug('Backend message: %s' % msg.name)
                msg = self.syncer.get_next_message()

    def can_sync(self):
        """Check if settings are enough to setup a syncing proccess"""
        return all([self.settings[e] for e in self.essentials])

    def init_sync(self):
        """Initialize syncer"""
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
            self.syncer_settings = syncer_settings
            # Check if syncer is ready, by consumming messages
            msg = syncer_.get_next_message()
            # while not msg:
            #     time.sleep(0.2)
            #     msg = syncer_.get_next_message()
            if msg:
                if isinstance(msg, messaging.LocalfsSyncDisabled):
                    LOG.debug('Local FS is dissabled, noooo!')
                    self.status['notification'] = 1
                elif isinstance(msg, messaging.PithosSyncDisabled):
                    LOG.debug('Pithos sync is disabled, noooooo!')
                    self.status['notification'] = 2
                else:
                    LOG.debug("Unexpected message: %s" % msg)
                    msg = None
            if msg:
                syncer_ = None
            else:
                syncer_.initiate_probe()
        finally:
            with SYNCERS.lock() as d:
                d[0] = syncer_

    # Syncer-related methods
    def get_status(self):
        if self.syncer and self.can_sync():
            self._consume_messages()
            self.status['paused'] = self.syncer.paused
            self.status['can_sync'] = self.can_sync()
        else:
            self.status.update(dict(
                synced=0, unsynced=0, paused=True, can_sync=False))
        return self.status

    def get_settings(self):
        return self.settings

    def set_settings(self, new_settings):
        """Set the settings and dump them to permanent storage if needed"""
        # Prepare setting save
        could_sync = self.syncer and self.can_sync()
        was_active = False
        if could_sync and not self.syncer.paused:
            was_active = True
            self.pause_sync()
        must_reset_syncing = self._essentials_changed(new_settings)

        # save settings
        self.settings.update(new_settings)
        self._dump_settings()

        # Restart
        if self.can_sync():
            if must_reset_syncing or not could_sync:
                self.init_sync()
            if was_active:
                self.start_sync()

    def pause_sync(self):
        self.syncer.stop_decide()
        LOG.debug('Wait open syncs to complete')
        self.syncer.wait_sync_threads()

    def start_sync(self):
        self.syncer.start_decide()

    def send_json(self, msg):
        LOG.debug('send: %s' % msg)
        self.send(json.dumps(msg))

    # Protocol handling methods
    def _post(self, r):
        """Handle POST requests"""
        if self.accepted:
            action = r['path']
            if action == 'shutdown':
                retry_on_locked_db(self.clean_db)
                # self._shutdown()
                # self.terminate()
                return
            {
                'start': self.start_sync,
                'pause': self.pause_sync
            }[action]()
            self.send_json({'OK': 200, 'action': 'post %s' % action})
        elif r['ui_id'] == self.ui_id:
            self.accepted = True
            Thread(target=self.heartbeat).start()
            self.send_json({'ACCEPTED': 202, 'action': 'post ui_id'})
            self._load_settings()
            if (not self.syncer) and self.can_sync():
                self.init_sync()
                if self.syncer:
                    self.start_sync()
        else:
            action = r.get('path', 'ui_id')
            self.send_json({'REJECTED': 401, 'action': 'post %s' % action})
            self.terminate()

    def _put(self, r):
        """Handle PUT requests"""
        if self.accepted:
            LOG.debug('put %s' % r)
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
        LOG.debug('recv: %s' % message)
        try:
            r = json.loads('%s' % message)
        except ValueError as ve:
            self.send_json({'BAD REQUEST': 400})
            LOG.error('JSON ERROR: %s' % ve)
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
            LOG.error('KEY ERROR: %s' % ke)
        except setup.ClientError as ce:
            action = '%s %s' % (
                method, r.get('path', 'ui_id' if 'ui_id' in r else ''))
            self.send_json({'%s' % ce: ce.status, 'action': action})
            return
        except Exception as e:
            self.send_json({'INTERNAL ERROR': 500})
            reason = '%s %s' % (method or '', r)
            LOG.error('EXCEPTION (%s): %s' % (reason, e))
            self.terminate()


def launch_server():
    """Launch the server in a separate process"""
    LOG.info('Start SessionHelper session')
    pid = os.fork()
    if not pid:
        server_path = os.path.join(CURPATH, 'scripts', 'server.py')
        os.execlp("python", "python", server_path)
