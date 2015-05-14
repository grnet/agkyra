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
import cmd
import sys
import logging
from agkyra import config


LOG = logging.getLogger(__name__)


class ConfigCommands:
    """Commands for handling Agkyra config options"""
    cnf = config.AgkyraConfig()

    def print_option(self, section, name, option):
        """Print a configuration option"""
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
                content = content[name]
            for option in content.keys():
                self.print_option(section, name, option)

    def list_section_type(self, section):
        """print the contents of a configuration section"""
        names = ['', ] if section in ('global', ) else self.cnf.keys(section)
        assert names, 'Section %s not found' % section
        for name in names:
            print section, name
            self.list_section(section, name)

    def list_sections(self):
        """List all configuration sections"""
        for section in self.cnf.sections():
            self.list_section_type(section)

    def set_global_setting(self, section, option, value):
        assert section in ('global'), 'Syntax error'
        self.cnf.set(section, option, value)
        self.cnf.write()

    def set_setting(self, section, name, option, value):
        assert section in self.cnf.sections(), 'Syntax error'
        self.cnf.set('%s.%s' % (section, name), option, value)
        self.cnf.write()

    def delete_global_option(self, section, option, yes=False):
        """Delete global option"""
        if (not yes and 'y' != raw_input(
                'Delete %s option %s? [y|N]: ' % (section, option))):
            sys.stderr.write('Aborted\n')
        else:
            self.cnf.remove_option(section, option)
            self.cnf.write()

    def delete_section_option(self, section, name, option, yes=False):
        """Delete a section (sync or cloud) option"""
        assert section in self.cnf.sections(), 'Syntax error'
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
        if (not yes and 'y' != raw_input(
                'Delete %s "%s"? [y|N]: ' % (section, name))):
            sys.stderr.write('Aborted\n')
        else:
            self.cnf.remove_option(section, name)
            self.cnf.write()


class AgkyraCLI(cmd.Cmd, WebSocketBaseClient):
    """The CLI for Agkyra is connected to a protocol server"""
    cnf_cmds = ConfigCommands()

    def preloop(self):
        """Prepare agkyra shell"""
        self.prompt = '\xe2\x9a\x93 '
        self.default('')

    def precmd(self):
        print 'PRE'

    def postcmd(self):
        print 'POST'

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
            LOG.debug('%s\n' % e)
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
            LOG.debug('%s\n' % e)
            sys.stderr.write(self.config_set.__doc__ + '\n')

    def config_delete(self, args):
        """Delete an option
        delete global OPTION [-y]               Delete a global option
        delete <cloud | sync> NAME [-y]         Delete a sync or cloud
        delete <cloud |sync> NAME OPTION [-y]   Delete a sync or cloud option
        """
        try:
            args.remove('-y')
            args.append(True)
        except ValueError:
            args.append(False)
        try:
            {
                3: self.cnf_cmds.delete_global_option if (
                    args[0] == 'global') else self.cnf_cmds.delete_section,
                4: self.cnf_cmds.delete_section_option
            }[len(args)](*args)
        except Exception as e:
            LOG.debug('%s\n' % e)
            sys.stderr.write(self.config_delete.__doc__ + '\n')

    def do_config(self, line):
        """Commands for managing the agkyra settings
        list   [global|cloud|sync [setting]]          List all or some settings
        set    <global|cloud|sync> <setting> <value>  Set a setting
        delete <global|cloud|sync> [setting]          Delete a setting or group
        """
        args = line.split(' ')
        try:
            method = getattr(self, 'config_' + args[0])
            method(args[1:])
        except AttributeError:
            self.do_help('config')


# AgkyraCLI().run_onecmd(sys.argv)

# or run a shell with
# AgkyraCLI().cmdloop()
