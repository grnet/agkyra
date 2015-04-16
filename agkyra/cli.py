import cmd
import sys
import logging
import json
from titanic import setup, syncer
from titanic.pithos_client import PithosFileClient
from titanic.localfs_client import FilesystemFileClient
import config
# from config import AgkyraConfig


logging.basicConfig(filename='agkyra.log', level=logging.DEBUG)
LOG = logging.getLogger(__name__)

setup.GLOBAL_SETTINGS_NAME = config.AGKYRA_DIR


class AgkyraCLI(cmd.Cmd):
    """The CLI for """

    cnf = config.AgkyraConfig()
    is_shell = False

    def init(self):
        """initialize syncer"""
        # Read settings
        sync = self.cnf.get('global', 'default_sync')
        LOG.info('Using sync: %s' % sync)
        cloud = self.cnf.get_sync(sync, 'cloud')
        url = self.cnf.get_cloud(cloud, 'url')
        token = self.cnf.get_cloud(cloud, 'token')
        container = self.cnf.get_sync(sync, 'container')
        directory = self.cnf.get_sync(sync, 'directory')

        # Prepare syncer settings
        self.settings = setup.SyncerSettings(
            sync, url, token, container, directory)
        LOG.info('Local: %s' % directory)
        LOG.info('Remote: %s of %s' % (container, url))
        # self.exclude = self.cnf.get_sync(sync, 'exclude')

        # Init syncer
        master = PithosFileClient(self.settings)
        slave = FilesystemFileClient(self.settings)
        self.syncer = syncer.FileSyncer(self.settings, master, slave)

    def preloop(self):
        """This runs when the shell loads"""
        if not self.is_shell:
            self.is_shell = True
            self.prompt = '\xe2\x9a\x93 '
            self.init()
        self.default('')

    def print_option(self, section, name, option):
        """Print a configuration option"""
        section = '%s.%s' % (section, name) if name else section
        value = self.cnf.get(section, option)
        print '  %s: %s' % (option, value)

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

    def do_list(self, line):
        """List current settings (\"help list\" for details)
        list global                 List all settings
        list global <option>        Get the value of this global option
        list cloud                  List all clouds
        list cloud <name>           List all options of a cloud
        list cloud <name> <option>  Get the value of this cloud option
        list sync                   List all syncs
        list sync <name>            List all options of a sync
        list sync <name> <option>   Get the value of this sync option
        """
        args = line.split()
        try:
            {
                0: self.list_sections,
                1: self.list_section_type,
                2: self.list_section,
                3: self.print_option
            }[len(args)](*args)
        except Exception as e:
            sys.stderr.write('%s\n' % e)
            cmd.Cmd.do_help(self, 'list')

    def set_global_setting(self, section, option, value):
        assert section in ('global'), 'Syntax error'
        self.cnf.set(section, option, value)

    def set_setting(self, section, name, option, value):
        assert section in self.sections(), 'Syntax error'
        self.cnf.set('%s.%s' % (section, name), option, value)

    def do_set(self, line):
        """Set a setting"""
        args = line.split()
        try:
            {
                3: self.set_global_setting,
                4: self.set_setting
            }[len(args)](*args)
            self.cnf.write()
        except Exception as e:
            sys.stderr.write('%s\n' % e)
            cmd.Cmd.do_help(self, 'set')

    def do_start(self, line):
        """Start syncing"""
        self.syncer.run()

    def do_pause(self, line):
        """Pause syncing"""

    def do_status(self, line):
        """Get current status (running/paused, progress)"""
        print 'I have no idea'

    # def do_shell(self, line):
    #     """Run system, shell commands"""
    #     if getattr(self, 'is_shell'):
    #         os.system(line)
    #     else:
    #         try:
    #             self.prompt = '\xe2\x9a\x93 '
    #             self.is_shell = True
    #         finally:
    #             self.init()
    #             self.cmdloop()

    def do_help(self, line):
        """List commands with \"help\" or detailed help with \"help cmd\""""
        if not line:
            self.default(line)
        cmd.Cmd.do_help(self, line)

    def do_quit(self, line):
        """Quit Agkyra shell"""
        return True

    def default(self, line):
        """print help"""
        sys.stderr.write('Usage:\t%s <command> [args]\n\n' % self.prompt)
        for arg in [c for c in self.get_names() if c.startswith('do_')]:
            sys.stderr.write('%s\t' % arg[3:])
            method = getattr(self, arg)
            sys.stderr.write(method.__doc__.split('\n')[0] + '\n')
        sys.stderr.write('\n')

    def emptyline(self):
        if not self.is_shell:
            return self.default('')

    def run_onecmd(self, argv):
        self.prompt = argv[0]
        self.init()
        self.onecmd(' '.join(argv[1:]))


# AgkyraCLI().run_onecmd(sys.argv)

# or run a shell with
AgkyraCLI().cmdloop()
