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
from re import match
from ConfigParser import Error
from kamaki.cli import config
# import Config, CLOUD_PREFIX
from kamaki.cli.config import Config
from kamaki.cli.utils import escape_ctrl_chars


CLOUD_PREFIX = config.CLOUD_PREFIX
config.HEADER = '# Agkyra configuration file version XXX\n'
AGKYRA_DIR = os.environ.get('AGKYRA_DIR', os.path.expanduser('~/.agkyra'))
CONFIG_PATH = '%s%sconfig.rc' % (AGKYRA_DIR, os.path.sep)
config.CONFIG_PATH = CONFIG_PATH
# neutralize kamaki CONFIG_ENV for this session
config.CONFIG_ENV = ''

SYNC_PREFIX = 'sync'
config.DEFAULTS = {
    'global': {
        'agkyra_dir': AGKYRA_DIR,
    },
    CLOUD_PREFIX: {
        # <cloud>: {
        #     'url': '',
        #     'token': '',
        #     whatever else may be useful in this context
        # },
        # ... more clouds
    },
    SYNC_PREFIX: {
        # <sync>: {
        #     'cloud': '',
        #     'container': '',
        #     'directory': ''
        # },
        # ... more syncs
    },
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
