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

from ws4py.client import WebSocketBaseClient
from agkyra.protocol import SessionHelper, launch_server
from agkyra.config import AGKYRA_DIR
from agkyra.syncer import utils
import subprocess
import sys
import os
import stat
import json
import logging

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

OSX_DEFAULT_NW_PATH = os.path.join(
    RESOURCES, 'nwjs', 'nwjs.app', 'Contents', 'MacOS', 'nwjs')
STANDARD_DEFAULT_NW_PATH = os.path.join(RESOURCES, 'nwjs', 'nw')
DEFAULT_NW_PATH = OSX_DEFAULT_NW_PATH if utils.isosx() \
    else STANDARD_DEFAULT_NW_PATH


class GUI(WebSocketBaseClient):
    """Launch the GUI when the SessionHelper server is ready"""

    def __init__(self, session, **kwargs):
        """Initialize the GUI Launcher
        :param session: session dict(ui_id=..., address=...) instance
        """
        super(GUI, self).__init__(session['address'])
        self.session_file = kwargs.get(
            'session_file', os.path.join(AGKYRA_DIR, 'session.info'))
        self.start = self.connect
        self.nw = kwargs.get('nw', DEFAULT_NW_PATH)
        self.gui_code = kwargs.get('gui_code', os.path.join(RESOURCES, 'nwgui'))
        assert not self._gui_running(session), (
            'Failed to initialize GUI, because another GUI is running')
        self._dump_session_file(session)

    def _gui_running(self, session):
        """Check if a session file with the same credentials already exists"""
        try:
            with open(self.session_file) as f:
                return session == json.load(f)
        except Exception:
            return False

    def _dump_session_file(self, session):
        """Create (overwrite) the session file for GUI use"""
        flags = os.O_CREAT | os.O_WRONLY
        mode = stat.S_IREAD | stat.S_IWRITE
        f = os.open(self.session_file, flags, mode)
        os.write(f, json.dumps(session))
        os.close(f)

    def clean_exit(self):
        """Clean up tracks of GUI"""
        try:
            os.remove(self.session_file)
            LOG.debug('Removed GUI session file')
        except Exception as e:
            LOG.warning('While cleaning GUI: %s' % e)
        self.close()

    def handshake_ok(self):
        """If handshake OK is, SessionHelper UP goes, so GUI launched can be"""
        LOG.debug('Protocol server is UP, running GUI')
        try:
            subprocess.call([self.nw, self.gui_code, self.session_file])
        finally:
            self.clean_exit()
        LOG.debug('GUI finished, close GUI wrapper connection')


def run(callback, debug):
    """Prepare SessionHelper and GUI and run them in the proper order"""
    launch_server(callback, debug)
    LOG.info('Client blocks until session is ready')
    session = SessionHelper().wait_session_to_load()
    assert session, 'UI server failed to load...'
    LOG.info('Server session is ready, setup the GUI session')
    gui = GUI(session)

    try:
        LOG.info('Start GUI')
        gui.start()
    except KeyboardInterrupt:
        LOG.info('Shutdown GUI')
        gui.clean_exit()

if __name__ == '__main__':
    logging.basicConfig(filename='agkyra.log', level=logging.DEBUG)
    run(os.path.abspath('gui/app'))
