.. _cli:

Command Line Interface (CLI)
============================

In this section it is assumed agkyra is installed and properly setup.

* For installation instructions, go to :ref:`installation`.
* For setup instructions, go to :ref:`setup`.

Agkyra CLI manages the agkyra back-end daemon (the module that
performs the actual syncing).

To get help, execute ``agkyra help`` from the command line. To get a list of
arguments, run it without any

.. code-block:: console

    $ agkyra help
    Help on agkyra GUI and CLI
        agkyra         Run agkyra with GUI (equivalent to "agkyra gui")
        agkyra <cmd>   Run a command through agkyra CLI

        To get help for agkyra commands:
            help <cmd>            for an individual command
            help <--list | -l>    for all commands

    Documented commands (type help <topic>):
    ========================================
    config  help  pause  shutdown  start  status gui


The CLI can be used independently or in parallel with the GUI. See
:ref:`guivscli` - for more information.

Commands and examples
---------------------

:command:`config list` - List all (or some) settings

.. code-block:: console

    List all settings

    $ agkyra config list
    global
      agkyra_dir: /home/user/.agkyra
      default_sync: default
      language: en
      ask_to_sync: on
    cloud default
      url: http://www.example.org/identity/v2.0
      token: us3r-t0k3n
    sync default
      directory: /my/local/dir
      container: remote_container
      cloud: default
    sync old_sync
      dicrectory: /my/old/dir
      container: another_container
      cloud: default

.. note:: Settings are organized in groups: ``global``, ``cloud`` and ``sync``

:command:`config set` - set a setting. Need to specify the exact group path

.. code-block:: console

    Set a new token for cloud "default"

    $ agkyra config set cloud default token n3w-us3r-t0k3n

:command:`config delete` - delete a setting or group of settings

.. code-block:: console

    Delete the "old_sync" sync

    $ agkyra config delete sync old_sync

:command:`status` - print daemon status. Status may be one of the following:

* ``Syncing``     The syncing daemon is running and is syncing your data
* ``Paused``      The syncing daemon is noticing your changes, but it doesn't sync them
* ``Not running`` No daemons are running

.. code-block:: console

    Check if a daemon is running

    $ agkyra status
    Not running

:command:`start` - launch a daemon if ``not running``, start syncing if ``paused``

.. code-block:: console

    Launch the syncing daemon

    $ agkyra start
    No Agkyra daemons running, starting one ... OK
    Syncing

..note:: Run "agkyra start daemon" to start a session as a daemon. After that,
    use the CLI from a separate console to manage the session, or launch a GUI.
    The GUI will automatically connect to the running session.

:command:`pause` - stop a daemon from ``syncing``, but keep it running

.. code-block:: console

    Pause a syncing daemon

    $ agkyra pause
    Pausing syncer ... OK
    Paused

:command:`shutdown` - shutdown daemon, if it's running (causes the GUI to terminate too)

.. code-block:: console

    Shutdown the daemon

    $ agkyra shutdown
    Shutting down Agkyra ... Stopped
