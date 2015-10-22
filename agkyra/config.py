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

"""
A Sync is a triplete consisting of at least the following:

* a cloud (a reference to a cloud set in the same config file)
* a container
* a local directory

Other parameters may also be set in the context of a sync.

The sync is identified by the "sync_id", which is a string

The operations of a sync are similar to the operations of a cloud, as they are
implemented in kamaki.cli.config
"""
import os
import sys
import imp
import stat
from re import match
from ConfigParser import Error
from kamaki.cli import config
# import Config, CLOUD_PREFIX
from kamaki.cli.config import Config
from kamaki.cli.utils import escape_ctrl_chars


CLOUD_PREFIX = config.CLOUD_PREFIX
config.HEADER = '# Agkyra configuration file version XXX\n'

HOME_DIR = os.path.expanduser('~')
DEFAULT_AGKYRA_DIR = os.path.join(HOME_DIR, ".agkyra")
AGKYRA_DIR = os.environ.get('AGKYRA_DIR', DEFAULT_AGKYRA_DIR)
AGKYRA_DIR = os.path.abspath(AGKYRA_DIR)

if os.path.exists(AGKYRA_DIR):
    if not os.path.isdir(AGKYRA_DIR):
        raise Exception("Cannot create dir '%s'; file exists" % AGKYRA_DIR)
else:
    os.makedirs(AGKYRA_DIR, mode=stat.S_IRWXU)

CONFIG_PATH = os.path.join(AGKYRA_DIR, 'config.rc')
config.CONFIG_PATH = CONFIG_PATH
# neutralize kamaki CONFIG_ENV for this session
config.CONFIG_ENV = ''

SYNC_PREFIX = 'sync'

if getattr(sys, 'frozen', False):
    # we are running in a |PyInstaller| bundle
    BASEDIR = sys._MEIPASS
else:
    # we are running in a normal Python environment
    BASEDIR = os.path.dirname(os.path.realpath(__file__))

RESOURCES = os.path.join(BASEDIR, 'resources')
defaults_file = os.path.join(RESOURCES, 'defaults.conf')
imp.load_source('default_settings', defaults_file)
from default_settings import DEFAULT_GLOBAL, DEFAULT_CLOUDS, DEFAULT_SYNCS
DEFAULT_GLOBAL['agkyra_dir'] = AGKYRA_DIR

config.DEFAULTS = {
    'global': DEFAULT_GLOBAL,
    CLOUD_PREFIX: DEFAULT_CLOUDS,
    SYNC_PREFIX: DEFAULT_SYNCS,
}


class InvalidSyncNameError(Error):
    """A valid sync name must pass through this regex: ([~@#$:.-\w]+)"""


class AgkyraConfig(Config):
    """
    Handle the config file for Agkyra, adding the notion of a sync

    A Sync is a triplete consisting of at least the following:

    * a cloud (a reference to a cloud set in the same config file)
    * a container
    * a local directory

    Other parameters may also be set in the context of a sync.

    The sync is identified by the sync id, which is a string

    The operations of a sync are similar to the operations of a cloud, as they
    are implemented in kamaki.cli.config
    """

    def __init__(self, *args, **kwargs):
        """Enhance Config to read SYNC sections"""
        Config.__init__(self, *args, **kwargs)

        for section in self.sections():
            r = self.sync_name(section)
            if r:
                for k, v in self.items(section):
                    self.set_sync(r, k, v)
                self.remove_section(section)

    @staticmethod
    def sync_name(full_section_name):
        """Get the sync name if the section is a sync, None otherwise"""
        if not full_section_name.startswith(SYNC_PREFIX + ' '):
            return None
        matcher = match(SYNC_PREFIX + ' "([~@#$.:\-\w]+)"', full_section_name)
        if matcher:
            return matcher.groups()[0]
        else:
            isn = full_section_name[len(SYNC_PREFIX) + 1:]
            raise InvalidSyncNameError('Invalid Cloud Name %s' % isn)

    def get(self, section, option):
        """Enhance Config.get to handle sync options"""
        value = self._overrides.get(section, {}).get(option)
        if value is not None:
            return value
        prefix = SYNC_PREFIX + '.'
        if section.startswith(prefix):
            return self.get_sync(section[len(prefix):], option)
        return config.Config.get(self, section, option)

    def set(self, section, option, value):
        """Enhance Config.set to handle sync options"""
        self.assert_option(option)
        prefix = SYNC_PREFIX + '.'
        if section.startswith(prefix):
            sync = self.sync_name(
                '%s "%s"' % (SYNC_PREFIX, section[len(prefix):]))
            return self.set_sync(sync, option, value)
        return config.Config.set(self, section, option, value)

    def get_sync(self, sync, option):
        """Get the option value from the given sync option
        :raises KeyError: if the sync or the option do not exist
        """
        r = self.get(SYNC_PREFIX, sync) if sync else None
        if r:
            return r[option]
        raise KeyError('Sync "%s" does not exist' % sync)

    def set_sync(self, sync, option, value):
        """Set the value of this option in the named sync.
        If the sync or the option do not exist, create them.
        """
        try:
            d = self.get(SYNC_PREFIX, sync) or dict()
        except KeyError:
            d = dict()
        self.assert_option(option)
        d[option] = value
        self.set(SYNC_PREFIX, sync, d)

    def remove_from_sync(self, sync, option):
        """Remove a sync option"""
        d = self.get(SYNC_PREFIX, sync)
        if isinstance(d, dict):
            d.pop(option)

    def safe_to_print(self):
        """Enhance Config.safe_to_print to handle syncs"""
        dump = Config.safe_to_print(self)
        for r, d in self.items(SYNC_PREFIX, include_defaults=False):
            dump += u'\n[%s "%s"]\n' % (SYNC_PREFIX, escape_ctrl_chars(r))
            for k, v in d.items():
                dump += u'%s = %s\n' % (
                    escape_ctrl_chars(k), escape_ctrl_chars(v))
        return dump


# if __name__ == '__main__':
#     cnf = AgkyraConfig()
#     config.Config.pretty_print(cnf)
#     cnf.set_sync('1', 'cloud', '~okeanos')
#     print cnf.get_sync('1', 'container')
#     cnf.set_sync('1', 'lala', 123)
#     cnf.remove_from_sync('1', 'lala')
#     cnf.write()
