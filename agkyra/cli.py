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

import cmd
import os
import sys
import logging
import argparse

from agkyra import protocol, protocol_client, gui, config


AGKYRA_DIR = config.AGKYRA_DIR
LOGGERFILE = os.path.join(AGKYRA_DIR, 'agkyra.log')
AGKYRA_LOGGER = logging.getLogger('agkyra')
HANDLER = logging.FileHandler(LOGGERFILE)
FORMATTER = logging.Formatter(
    "%(name)s:%(lineno)s %(levelname)s:%(asctime)s:%(message)s")
HANDLER.setFormatter(FORMATTER)
AGKYRA_LOGGER.addHandler(HANDLER)

logging.getLogger('astakosclient').addHandler(logging.NullHandler())

LOGGER = logging.getLogger(__name__)
STATUS = protocol.STATUS
NOTIFICATION = protocol.COMMON['NOTIFICATION']

remaining = lambda st: st['unsynced'] - (st['synced'] + st['failed'])


class ConfigError(protocol_client.UIClientError):
    """Error with config settings"""


class ConfigCommands(object):
    """Commands for handling Agkyra config options"""
    cnf = config.AgkyraConfig()

    def _validate_section(self, section, err_msg='"%s" is not a valid section'):
        """:raises ConfigError: if the section is invalid"""
        if not self.cnf.has_section(section):
            raise ConfigError(err_msg % section)

    def _assert_section_name(self, section, name, err_msg='%s "%s" not found'):
        """:raises ConfigError: if the section name does not exist"""
        if name not in self.cnf.keys(section):
            raise ConfigError(err_msg % (section, name))

    def _assert_has_option(
            self, section, name, option, err_msg='%s "%s" has no option "%s"'):
        """:raises ConfigError: if the option does not exist"""
        if option not in self.cnf.get(section, name):
            raise ConfigError(err_msg % (section, name, option))

    def print_option(self, section, name, option):
        """Print a configuration option"""
        self._validate_section(section)
        self._assert_section_name(section, name or option)
        if name:
            self._assert_has_option(section, name, option)
        section = '%s.%s' % (section, name) if name else section
        value = self.cnf.get(section, option)
        sys.stdout.write('  %s: %s\n' % (option, value))

    def list_section(self, section, name):
        """list contents of a section"""
        content = dict(self.cnf.items(section))
        if section in 'global' and name:
            self.print_option(section, '', name)
        else:
            if name:
                self._assert_section_name(section, name)
                content = content[name]
            for option in content.keys():
                self.print_option(section, name, option)

    def list_section_type(self, section):
        """Print the contents of a configuration section"""
        names = ['', ] if section in ('global', ) else self.cnf.keys(section)
        if not names:
            raise ConfigError('Section %s not found' % section)
        for name in names:
            sys.stdout.write('%s %s\n' % (section, name))
            sys.stdout.flush()
            self.list_section(section, name)

    def list_sections(self):
        """List all configuration sections"""
        for section in self.cnf.sections():
            self.list_section_type(section)

    def set_global_setting(self, section, option, value):
        assert section == 'global', 'section %s should be global"' % section
        self.cnf.set(section, option, value)
        self.cnf.write()

    def set_setting(self, section, name, option, value):
        self._validate_section(section)
        self.cnf.set('%s.%s' % (section, name), option, value)
        self.cnf.write()

    def delete_global_option(self, section, option, yes=False):
        """Delete global option"""
        assert section == 'global', 'Section must be global, not %s' % section
        self._assert_section_name(
            section, option, '%s option "%s" does not exist')
        if (not yes and 'y' != raw_input(
                'Delete %s option %s? [y|N]: ' % (section, option))):
            sys.stderr.write('Aborted\n')
        else:
            self.cnf.remove_option(section, option)
            self.cnf.write()

    def delete_section_option(self, section, name, option, yes=False):
        """Delete a section (sync or cloud) option"""
        self._validate_section(section)
        self._assert_section_name(section, name)
        self._assert_has_option(section, name, option)
        if (not yes and 'y' != raw_input(
                'Delete %s of %s "%s"? [y|N]: ' % (option, section, name))):
            sys.stderr.write('Aborted\n')
        else:
            if section == config.CLOUD_PREFIX:
                self.cnf.remove_from_cloud(name, option)
            elif section == config.SYNC_PREFIX:
                self.cnf.remove_from_sync(name, option)
            else:
                self.cnf.remove_option('%s.%s' % (section, name), option)
            self.cnf.write()

    def delete_section(self, section, name, yes=False):
        """Delete a section (sync or cloud)"""
        self._validate_section(section)
        self._assert_section_name(section, name)
        if (not yes and 'y' != raw_input(
                'Delete %s "%s"? [y|N]: ' % (section, name))):
            sys.stderr.write('Aborted\n')
        else:
            self.cnf.remove_option(section, name)
            self.cnf.write()


from functools import wraps

def handle_UI_error(func):
    def inner(*args, **kw):
        try:
            return func(*args, **kw)
        except protocol_client.UIClientError as uice:
            msg = '%s' % uice
            LOGGER.debug(msg)
            sys.stderr.write(msg)
            sys.stderr.flush()
    return inner


class AgkyraCLI(cmd.Cmd):
    """The CLI for Agkyra is connected to a protocol server"""
    cnf_cmds = ConfigCommands()
    helper = protocol.SessionHelper()

    def __init__(self, *args, **kwargs):
        self.callback = kwargs.pop('callback', sys.argv[0])
        self.args = kwargs.pop('parsed_args', None)
        AGKYRA_LOGGER.setLevel(logging.DEBUG
                               if self.args.debug else logging.INFO)
        cmd.Cmd.__init__(self, *args, **kwargs)

    @staticmethod
    def parse_args():
        parser = argparse.ArgumentParser(
            description='Agkyra syncer launcher', add_help=False)
        parser.add_argument(
            '--help', '-h',
            action='store_true', help='Help on agkyra syntax and usage')
        parser.add_argument(
            '--debug', '-d',
            action='store_true', help='set logging level to "debug"')
        parser.add_argument('cmd', nargs="*")

        for terms in (['help', ], ['config', 'delete']):
            if not set(terms).difference(sys.argv):
                {
                    'help': lambda: parser.add_argument(
                        '--list', '-l',
                        action='store_true', help='List all commands'),
                    'config_delete': lambda: parser.add_argument(
                        '--yes', '-y',
                        action='store_true', help='Yes to all questions')
                }['_'.join(terms)]()

        return parser.parse_args()

    def must_help(self, command):
        if self.args.help:
            self.do_help(command)
            return True
        return False

    def launch_daemon(self):
        """Launch the agkyra protocol server"""
        LOGGER.info('Starting the agkyra daemon')
        session_daemon = self.helper.create_session_daemon()
        if session_daemon:
            session_daemon.start()
            LOGGER.info('Daemon is shut down')
        else:
            LOGGER.info('Another daemon is running, aborting')

    @property
    def client(self):
        """Return the helper client instace or None"""
        self._client = getattr(self, '_client', None)
        if not self._client:
            session = self.helper.load_active_session()
            if session:
                self._client = protocol_client.UIClient(session)
                self._client.connect()
        return self._client

    def do_help(self, line):
        """Help on agkyra GUI and CLI
        agkyra         Run agkyra with GUI (equivalent to "agkyra gui")
        agkyra <cmd>   Run a command through agkyra CLI

        To get help on agkyra commands:
            help <cmd>            for an individual command
            help <--list | -l>    for all commands
        """
        if getattr(self.args, 'list', None):
            self.args.list = None
            prefix = 'do_'
            for c in self.get_names():
                if c.startswith(prefix):
                    actual_name = c[len(prefix):]
                    sys.stderr.write('- %s -\n' % actual_name)
                    self.do_help(actual_name)
        else:
            if not line:
                cmd.Cmd.do_help(self, 'help')
            cmd.Cmd.do_help(self, line)

    def emptyline(self):
        if self.must_help(''):
            return
        return self.do_gui('')

    def default(self, line):
        self.do_help(line)

    def config_list(self, args):
        """List (all or some) options
        list                                List all options
        list <global | cloud | sync>        List global | cloud | sync options
        list global OPTION                  Get global option
        list <cloud | sync> NAME            List options a cloud or sync
        list <cloud | sync> NAME OPTION     List an option from a cloud or sync
        """
        try:
            {
                0: self.cnf_cmds.list_sections,
                1: self.cnf_cmds.list_section_type,
                2: self.cnf_cmds.list_section,
                3: self.cnf_cmds.print_option
            }[len(args)](*args)
        except Exception as e:
            LOGGER.debug('%s\n' % e)
            if isinstance(e, ConfigError):
                raise
            sys.stderr.write(self.config_list.__doc__ + '\n')

    def config_set(self, args):
        """Set an option
        set global OPTION VALUE                 Set a global option
        set <cloud | sync> NAME OPTION VALUE    Set an option on cloud or sync
                                                Creates a sync or cloud, if it
                                                does not exist
        """
        try:
            {
                3: self.cnf_cmds.set_global_setting,
                4: self.cnf_cmds.set_setting
            }[len(args)](*args)
        except Exception as e:
            LOGGER.debug('%s\n' % e)
            if isinstance(e, ConfigError):
                raise
            sys.stderr.write(self.config_set.__doc__ + '\n')

    def config_delete(self, args):
        """Delete an option
        delete global OPTION [-y]               Delete a global option
        delete <cloud | sync> NAME [-y]         Delete a sync or cloud
        delete <cloud |sync> NAME OPTION [-y]   Delete a sync or cloud option
        """
        args.append(self.args.yes)
        try:
            {
                3: self.cnf_cmds.delete_global_option if (
                    args[0] == 'global') else self.cnf_cmds.delete_section,
                4: self.cnf_cmds.delete_section_option
            }[len(args)](*args)
        except Exception as e:
            LOGGER.debug('%s\n' % e)
            if isinstance(e, ConfigError):
                raise
            sys.stderr.write(self.config_delete.__doc__ + '\n')

    def do_config(self, line):
        """Commands for managing the agkyra settings
        list   [global|cloud|sync [setting]]          List all or some settings
        set    <global|cloud|sync> <setting> <value>  Set a setting
        delete <global|cloud|sync> [setting]          Delete a setting or group
        """
        if self.must_help('config'):
            return
        args = line.split(' ')
        try:
            method = getattr(self, 'config_' + args[0])
            method(args[1:])
        except AttributeError:
            self.do_help('config')
        except ConfigError as ce:
            sys.stderr.write('%s\n' % ce)
            sys.stderr.flush()

    def do_status(self, line):
        """Get Agkyra client status. Status may be one of the following:
        Syncing     There is a process syncing right now
        Paused      Notifiers are active but syncing is paused
        Not running No active processes
        """
        self._status(line)

    @handle_UI_error
    def _status(self, line):
        if self.must_help('status'):
            return
        client = self.client
        status, msg = client.get_status() if client else None, 'Not running'
        if status:
            msg = NOTIFICATION[str(status['code'])]
            diff = remaining(status)
            if diff:
                msg = '%s, %s remaining' % (msg, diff)
        sys.stdout.write('%s\n' % msg)
        sys.stdout.flush()

    def do_start(self, line):
        """Start the session, set it in syncing mode
        start         Start syncing. If daemon is down, start it up
        start daemon  Start the agkyra daemon and wait
        """
        self._start(line)

    @handle_UI_error
    def _start(self, line):
        if self.must_help('start'):
            return
        if line in ['daemon']:
            return self.launch_daemon()
        if line:
            sys.stderr.write("Unrecognized subcommand '%s'.\n" % line)
            sys.stderr.flush()
            return
        client = self.client
        if not client:
            sys.stderr.write('No Agkyra daemons running, starting one')
            protocol.launch_server(self.callback, self.args.debug)
            sys.stderr.write(' ... ')
            self.helper.wait_session_to_load()
            sys.stderr.write('OK\n')
        else:
            status = client.get_status()
            if status['code'] == STATUS['PAUSED']:
                client.start()
                sys.stderr.write('Starting syncer ... ')
                try:
                    client.wait_until_syncing()
                    sys.stderr.write('OK\n')
                except protocol_client.UIClientError as uice:
                    sys.stderr.write('%s\n' % uice)
            else:
                sys.stderr.write('Already ')
        sys.stderr.flush()
        self.do_status(line)

    def do_pause(self, line):
        """Pause a session (stop it from syncing, but keep it running)"""
        self._pause(line)

    @handle_UI_error
    def _pause(self, line):
        if self.must_help('pause'):
            return
        client = self.client
        if client:
            status = client.get_status()
            if status['code'] == STATUS['PAUSED']:
                sys.stderr.write('Already ')
            else:
                client.pause()
                sys.stderr.write('Pausing syncer ... ')
                try:
                    client.wait_until_paused()
                    sys.stderr.write('OK\n')
                except protocol_client.UIClientError as uice:
                    sys.stderr.write('%s\n' % uice)
        sys.stderr.flush()
        self.do_status(line)

    def do_shutdown(self, line):
        """Shutdown Agkyra, if it is running"""
        self._shutdown(line)

    @handle_UI_error
    def _shutdown(self, line):
        if self.must_help('shutdown'):
            return
        client = self.client
        if client:
            client.shutdown()
            sys.stderr.write('Shutting down Agkyra ... ')
            success = self.helper.wait_session_to_stop()
            sys.stderr.write('Stopped' if success else 'Still up (timed out)')
            sys.stderr.write('\n')
        else:
            sys.stderr.write('Not running\n')
        sys.stderr.flush()


    # Systemic commands
    def do_gui(self, line):
        """Launch the agkyra GUI
        Only one GUI instance can run at a time.
        If an agkyra daemon is already running, the GUI will use it.
        """
        if self.must_help('gui'):
            return
        session = self.helper.load_active_session()
        if not session:
            self._start('')
            session = self.helper.wait_session_to_load()
        if session:
            LOGGER.info('Start new GUI')
            new_gui = gui.GUI(session, debug=self.args.debug)
            try:
                new_gui.start()
            except KeyboardInterrupt:
                LOGGER.info('GUI interrupted by user')
                sys.stderr.write('GUI interrupted by user, exiting\n')
                sys.stderr.flush()
                new_gui.clean_exit()
            LOGGER.info('GUI is shutdown')
            if self.client:
                self._shutdown('')
        else:
            sys.stderr.write('Session failed to load\n')
            sys.stderr.flush()
