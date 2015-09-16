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
import sys
import json
import logging
import subprocess
from agkyra.syncer import (
    syncer, setup, pithos_client, localfs_client, messaging, utils)
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

LOG = logging.getLogger(__name__)
SYNCERS = utils.ThreadSafeDict()

with open(os.path.join(RESOURCES, 'ui_data/common_en.json')) as f:
    COMMON = json.load(f)
STATUS = COMMON['STATUS']


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

        retry_on_locked_db(self._init_db_relation)

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
        """Periodically update the session database timestamp"""
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
            "sync_on_start": <true|false>
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
            "sync_on_start": <true|false>
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
    session_db, session_relation = None, None
    accepted = False
    settings = dict(
        token=None, url=None,
        container=None, directory=None,
        exclude=None, sync_on_start=True, language="en")
    cnf = AgkyraConfig()
    essentials = ('url', 'token', 'container', 'directory')

    def get_status(self, key=None):
        """:return: updated status dict or value of specified key"""
        if self.syncer and self.can_sync():
            self._consume_messages()
            with self.status.lock() as d:
                LOG.debug('Status was %s' % d['code'])
                if d['code'] in (
                        STATUS['UNINITIALIZED'], STATUS['INITIALIZING']):
                    if self.syncer.paused:
                        d['code'] = STATUS['PAUSED']
                    elif d['code'] != STATUS['PAUSING'] or (
                            d['unsynced'] == d['synced'] + d['failed']):
                        d['code'] = STATUS['SYNCING']
        with self.status.lock() as d:
            LOG.debug('Status is now %s' % d['code'])
            return d.get(key, None) if key else dict(d)

    def set_status(self, **kwargs):
        with self.status.lock() as d:
            LOG.debug('CHANGING STATUS TO %s' % kwargs)
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
        LOG.debug('Remove current session trace')
        db = sqlite3.connect(self.session_db)
        db.execute('BEGIN')
        db.execute('DELETE FROM %s WHERE ui_id="%s"' % (
            self.session_relation, self.ui_id))
        db.commit()
        db.close()

    def shutdown_syncer(self, syncer_key=0):
        """Shutdown the syncer backend object"""
        LOG.debug('Shutdown syncer')
        with SYNCERS.lock() as d:
            syncer = d.pop(syncer_key, None)
            if syncer and self.can_sync():
                syncer.stop_all_daemons()
                LOG.debug('Wait open syncs to complete')
                syncer.wait_sync_threads()

    def heartbeat(self):
        """Update session DB timestamp as long as session is alive"""
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
        self.shutdown_syncer()
        self.set_status(code=STATUS['UNINITIALIZED'])
        self.close()

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
            self.set_status(code=STATUS['SETTINGS MISSING'])
        try:
            self.settings['token'] = self.cnf.get_cloud(cloud, 'token')
        except Exception:
            self.settings['url'] = None
            self.set_status(code=STATUS['SETTINGS MISSING'])

        self.settings['sync_on_start'] = (
            self.cnf.get('global', 'sync_on_start') == 'on')
        self.settings['language'] = self.cnf.get('global', 'language')

        # for option in ('container', 'directory', 'exclude'):
        for option in ('container', 'directory'):
            try:
                self.settings[option] = self.cnf.get_sync(sync, option)
            except KeyError:
                LOG.debug('No %s is set' % option)
                self.set_status(code=STATUS['SETTINGS MISSING'])

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

        self.cnf.set('global', 'language', self.settings.get('language', 'en'))
        sync_on_start = self.settings.get('sync_on_start', False)
        self.cnf.set(
            'global', 'sync_on_start', 'on' if sync_on_start else 'off')

        if changes:
            self.cnf.write()
            LOG.debug('Settings saved')
        else:
            LOG.debug('No setting changes spotted')

    def _essentials_changed(self, new_settings):
        """Check if essential settings have changed in new_settings"""
        return all([
            self.settings[e] == self.settings[e] for e in self.essentials])

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
                    LOG.debug('UNSYNCED +1 %s' % getattr(msg, 'objname', ''))
                    self.set_status(unsynced=self.get_status('unsynced') + 1)
                elif isinstance(msg, messaging.AckSyncMessage):
                    LOG.debug('SYNCED +1 %s' % getattr(msg, 'objname', ''))
                    self.set_status(synced=self.get_status('synced') + 1)
                elif isinstance(msg, messaging.SyncErrorMessage):
                    LOG.debug('FAILED +1 %s' % getattr(msg, 'objname', ''))
                    self.set_status(failed=self.get_status('failed') + 1)
                elif isinstance(msg, messaging.LocalfsSyncDisabled):
                    LOG.debug('STOP BACKEND, %s'% getattr(msg, 'objname', ''))
                    LOG.debug('CHANGE STATUS TO: %s' % STATUS['DIRECTORY ERROR'])
                    self.set_status(code=STATUS['DIRECTORY ERROR'])
                    self.syncer.stop_all_daemons()
                elif isinstance(msg, messaging.PithosSyncDisabled):
                    LOG.debug('STOP BACKEND, %s'% getattr(msg, 'objname', ''))
                    self.set_status(code=STATUS['CONTAINER ERROR'])
                    self.syncer.stop_all_daemons()
                LOG.debug('Backend message: %s %s' % (msg.name, type(msg)))
                # Limit the amount of messages consumed each time
                max_consumption -= 1
                if max_consumption:
                    msg = self.syncer.get_next_message()
                else:
                    break

    def can_sync(self):
        """Check if settings are enough to setup a syncing proccess"""
        return all([self.settings[e] for e in self.essentials])

    def init_sync(self):
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
            self.syncer_settings = syncer_settings
            # Check if syncer is ready, by consuming messages
            local_ok, remote_ok = False, False
            for i in range(2):

                LOG.debug('Get message %s' % (i + 1))
                msg = syncer_.get_next_message(block=True)
                LOG.debug('Got message: %s' % msg)

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
                    LOG.error('Unexpected message %s' % msg)
                    self.set_status(code=STATUS['CRITICAL ERROR'])
                    break
            if local_ok and remote_ok:
                syncer_.initiate_probe()
                self.set_status(code=STATUS['SYNCING'])
            else:
                syncer_ = None
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

    def _pause_syncer(self):
        syncer_ = self.syncer
        syncer_.stop_decide()
        LOG.debug('Wait open syncs to complete')
        syncer_.wait_sync_threads()

    def pause_sync(self):
        """Pause syncing (assuming it is up and running)"""
        if self.syncer:
            self.syncer.stop_decide()
            self.set_status(code=STATUS['PAUSING'])

    def start_sync(self):
        """Start syncing"""
        self.syncer.start_decide()

    def force_sync(self):
        """Force syncing, assuming there is a directory or container problem"""
        self.set_status(code=STATUS['INITIALIZING'])
        self.syncer_settings.purge_db_archives_and_enable()
        self.init_sync()
        if self.syncer:
            self.syncer.start_decide()
            self.set_status(code=STATUS['SYNCING'])
        else:
            self.set_status(code=STATUS['CRITICAL ERROR'])

    def send_json(self, msg):
        LOG.debug('send: %s' % msg)
        self.send(json.dumps(msg))

    # Protocol handling methods
    def _post(self, r):
        """Handle POST requests"""
        if self.accepted:
            action = r['path']
            if action == 'shutdown':
                # Clean db to cause syncer backend to shut down
                self.set_status(code=STATUS['SHUTTING DOWN'])
                retry_on_locked_db(self.clean_db)
                # self._shutdown()
                # self.terminate()
                return
            {
                'start': self.start_sync,
                'pause': self.pause_sync,
                'force': self.force_sync
            }[action]()
            self.send_json({'OK': 200, 'action': 'post %s' % action})
        elif r['ui_id'] == self.ui_id:
            self.accepted = True
            Thread(target=self.heartbeat).start()
            self.send_json({'ACCEPTED': 202, 'action': 'post ui_id'})
            self._load_settings()
            if (not self.syncer) and self.can_sync():
                self.init_sync()
                if self.syncer and self.settings['sync_on_start']:
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


def launch_server(callback, debug):
    """Launch the server in a separate process"""
    LOG.info('Start SessionHelper session')
    if utils.iswin():
        command = [callback]
        if debug:
            command.append('-d')
        command.append("server")
        subprocess.Popen(command,
                         close_fds=True)
    else:
        pid = os.fork()
        if not pid:
            command = [callback, callback]
            if debug:
                command.append('-d')
            command.append("server")
            os.execlp(*command)
