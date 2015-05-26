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
from agkyra.protocol import SessionHelper
from agkyra.config import AGKYRA_DIR
import subprocess
import os
import stat
import json
import logging

CURPATH = os.path.dirname(os.path.abspath(__file__))
LOG = logging.getLogger(__name__)


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
        self.nw = kwargs.get(
            'nw', os.path.join(os.path.join(CURPATH, 'nwjs'), 'nw'))
        self.gui_code = kwargs.get('gui_code', os.path.join(CURPATH, 'gui'))
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


def run():
    """Prepare SessionHelper and GUI and run them in the proper order"""
    helper = SessionHelper()
    gui = GUI(helper.session)

    LOG.info('Start SessionHelper session')
    helper.start()

    try:
        LOG.info('Start GUI')
        gui.start()
    except KeyboardInterrupt:
        LOG.info('Shutdown GUI')
        gui.clean_exit()
    LOG.info('Shutdown SessionHelper server')
    helper.shutdown()

if __name__ == '__main__':
    logging.basicConfig(filename='agkyra.log', level=logging.DEBUG)
    run(os.path.abspath('gui/app'))
