from ws4py.websocket import WebSocket
import json
import logging
from os.path import abspath
from agkyra.syncer import (
    syncer, setup, pithos_client, localfs_client, messaging)
from agkyra.config import AgkyraConfig


LOG = logging.getLogger(__name__)


class WebSocketProtocol(WebSocket):
    """Helper-side WebSocket protocol for communication with GUI:

    -- INTERRNAL HANDSAKE --
    GUI: {"method": "post", "gui_id": <GUI ID>}
    HELPER: {"ACCEPTED": 202, "method": "post"}" or
        "{"REJECTED": 401, "action": "post gui_id"}

    -- SHUT DOWN --
    GUI: {"method": "post", "path": "shutdown"}

    -- PAUSE --
    GUI: {"method": "post", "path": "pause"}
    HELPER: {"OK": 200, "action": "post pause"} or error

    -- start --
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
        "progress": <int>,
        "paused": <boolean>,
        "action": "get status"} or
        {<ERROR>: <ERROR CODE>, "action": "get status"}
    """

    gui_id = None
    accepted = False
    settings = dict(
        token=None, url=None,
        container=None, directory=None,
        exclude=None)
    status = dict(progress=0, synced=0, unsynced=0, paused=True, can_sync=False)
    file_syncer = None
    cnf = AgkyraConfig()
    essentials = ('url', 'token', 'container', 'directory')

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

        for option in ('container', 'directory', 'exclude'):
            try:
                self.settings[option] = self.cnf.get_sync(sync, option)
            except KeyError:
                LOG.debug('No %s is set' % option)

        LOG.debug('Finished loading settings')

    def _dump_settings(self):
        LOG.debug('Saving settings')
        if not self.settings.get('url', None):
            LOG.debug('No settings to save')
            return

        sync = self._get_default_sync()
        cloud = self._get_sync_cloud(sync)

        try:
            old_url = self.cnf.get_cloud(cloud, 'url') or ''
        except KeyError:
            old_url = self.settings['url']

        while old_url != self.settings['url']:
            cloud = '%s_%s' % (cloud, sync)
            try:
                self.cnf.get_cloud(cloud, 'url')
            except KeyError:
                break

        self.cnf.set_cloud(cloud, 'url', self.settings['url'])
        self.cnf.set_cloud(cloud, 'token', self.settings['token'] or '')
        self.cnf.set_sync(sync, 'cloud', cloud)

        for option in ('directory', 'container', 'exclude'):
            self.cnf.set_sync(sync, option, self.settings[option] or '')

        self.cnf.write()
        LOG.debug('Settings saved')

    def _essentials_changed(self, new_settings):
        """Check if essential settings have changed in new_settings"""
        return all([
            self.settings[e] == self.settings[e] for e in self.essentials])

    def _update_statistics(self):
        """Update statistics by consuming and understanding syncer messages"""
        if self.can_sync():
            msg = self.syncer.get_next_message()
            if not msg:
                if self.status['unsynced'] == self.status['synced']:
                    self.status['unsynced'] = 0
                    self.status['synced'] = 0
            while (msg):
                if isinstance(msg, messaging.SyncMessage):
                    LOG.info('Start syncing "%s"' % msg.objname)
                    self.status['unsynced'] += 1
                elif isinstance(msg, messaging.AckSyncMessage):
                    LOG.info('Finished syncing "%s"' % msg.objname)
                    self.status['synced'] += 1
                elif isinstance(msg, messaging.CollisionMessage):
                    LOG.info('Collision for "%s"' % msg.objname)
                elif isinstance(msg, messaging.ConflictStashMessage):
                    LOG.info('Conflict for "%s"' % msg.objname)
                else:
                    LOG.debug('Consumed msg %s' % msg)
                msg = self.syncer.get_next_message()

    def can_sync(self):
        """Check if settings are enough to setup a syncing proccess"""
        return all([self.settings[e] for e in self.essentials])

    def init_sync(self):
        """Initialize syncer"""
        sync = self._get_default_sync()
        syncer_settings = setup.SyncerSettings(
            sync,
            self.settings['url'], self.settings['token'],
            self.settings['container'], self.settings['directory'],
            ignore_ssl=True)
        master = pithos_client.PithosFileClient(syncer_settings)
        slave = localfs_client.LocalfsFileClient(syncer_settings)
        self.syncer = syncer.FileSyncer(syncer_settings, master, slave)
        self.syncer_settings = syncer_settings
        self.syncer.initiate_probe()

    # Syncer-related methods
    def get_status(self):
        self._update_statistics()
        self.status['paused'] = self.syncer.paused
        self.status['can_sync'] = self.can_sync()
        return self.status

    def get_settings(self):
        return self.settings

    def set_settings(self, new_settings):
        # Prepare setting save
        could_sync = self.can_sync()
        was_active = not self.syncer.paused
        if could_sync and was_active:
            self.pause_sync()
        must_reset_syncing = self._essentials_changed(new_settings)

        # save settings
        self.settings = new_settings
        self._dump_settings()

        # Restart
        if self.can_sync():
            if must_reset_syncing or not could_sync:
                self.init_sync()
            elif was_active:
                self.start_sync()

    def pause_sync(self):
        self.syncer.stop_decide()
        LOG.debug('Wait open syncs to complete')
        self.syncer.wait_sync_threads()

    def start_sync(self):
        self.syncer.start_decide()

    # WebSocket connection methods
    def opened(self):
        LOG.debug('Helper: connection established')

    def closed(self, *args):
        LOG.debug('Helper: connection closed')

    def send_json(self, msg):
        LOG.debug('send: %s' % msg)
        self.send(json.dumps(msg))

    # Protocol handling methods
    def _post(self, r):
        """Handle POST requests"""
        if self.accepted:
            action = r['path']
            if action == 'shutdown':
                if self.can_sync():
                    self.syncer.stop_all_daemons()
                    LOG.debug('Wait open syncs to complete')
                    self.syncer.wait_sync_threads()
                self.close()
                return
            {
                'start': self.start_sync,
                'pause': self.pause_sync
            }[action]()
            self.send_json({'OK': 200, 'action': 'post %s' % action})
        elif r['gui_id'] == self.gui_id:
            self._load_settings()
            self.accepted = True
            self.send_json({'ACCEPTED': 202, 'action': 'post gui_id'})
            if self.can_sync():
                self.init_sync()
                self.pause_sync()
        else:
            action = r.get('path', 'gui_id')
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
            self.send_json({'UNAUTHORIZED': 401, 'action': 'put %s' % action})
            self.terminate()

    def _get(self, r):
        """Handle GET requests"""
        action = r.pop('path')
        if not self.accepted:
            self.send_json({'UNAUTHORIZED': 401, 'action': 'get %s' % action})
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
            self.send_json({'BAD REQUEST': 400})
            LOG.error('KEY ERROR: %s' % ke)
        except Exception as e:
            self.send_json({'INTERNAL ERROR': 500})
            LOG.error('EXCEPTION: %s' % e)
            self.terminate()
