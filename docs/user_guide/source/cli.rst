.. _cli:

Command Line Interface (CLI)
============================

In this section it is assumed agkyra is installed and properly setup.

* For installation instructions, go to :ref:`installation`.
* For setup instructions, go to :ref:`setup`.

Agkyra CLI manages the agkyra back-end daemon (the module that
performs the actual syncing).

To run it, execute ``agkyra-cli`` from the command line. To get a list of
arguments, run it without any

.. code-block:: console

    $ agkyra-cli
    Get help
                help <cmd>            for an individual command
                help <--list | -l>    for all commands

    Documented commands (type help <topic>):
    ========================================
    config  help  pause  shutdown  start  status


The CLI can be used independently or in parallel with the GUI. See
:ref:`guivscli` - for more information.

Commands and examples
---------------------

:command:`config list` - List all (or some) settings

.. code-block:: console

    List all settings

    $ agkyra-cli config list
    global
      agkyra_dir: /home/user/.agkyra
      default_sync: default
      language: en
      sync_on_start: on
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

    $ agkyra-cli config set cloud default token n3w-us3r-t0k3n

:command:`config delete` - delete a setting or group of settings

.. code-block:: console

    Delete the "old_sync" sync

    $ agkyra-cli config delete sync old_sync

:command:`status` - print daemon status. Status may be one of the following:

* ``Syncing``     The syncing daemon is running and is syncing your data
* ``Paused``      The syncing daemon is noticing your changes, but it doesn't sync them
* ``Not running`` No daemons are running

.. code-block:: console

    Check if a daemon is running

    $ agkyra-cli status
    Not running

:command:`start` - launch a daemon if ``not running``, start syncing if ``paused``

.. code-block:: console

    Launch the syncing daemon

    $ agkyra-cli start
    No Agkyra daemons running, starting one ... OK
    Syncing

:command:`pause` - stop a daemon from ``syncing``, but keep it running

.. code-block:: console

    Pause a syncing daemon

    $ agkyra-cli pause
    Pausing syncer ... OK
    Paused

:command:`shutdown` - shutdown daemon, if it's running (causes the GUI to terminate too)

.. code-block:: console

    Shutdown the daemon

    $ agkyra-cli shutdown
    Shutting down Agkyra ... Stopped
