Settings
========

Settings are organized in three categories: ``global``, ``cloud`` and ``sync``.

``Global`` settings affect the behavior of the application in general

``Clouds`` are URL/token pairs and they describe the access of a user to a remote
Synnefo deployment. Each cloud has a name.

``Syncs`` correlate a remote container to a local directory. Each sync has a
name.

Global
------

Global settings can affect the behavior of the back-end or the front-end.
Currently, the global settings are the following:

:dfn:`agkyra_dir` The program space directory, defined automatically. The program database and logs are stored in there.
    default: ``$HOME/.agkyra/``

:dfn:`default_sync` The name of the ``sync`` to use in the application. Currently, only one synchronization can be in effect.
    default: if not set by the user, it is decided automatically

:dfn:`language` The language of the GUI menu, windows and notifications. There are currently two supported languages, Greek (**el**) and English (**en**). The CLI is always in english.
    default: ``en``

:dfn:`ask_to_sync` GUI only flag. Switch on a dialogue box asking user whether syncing should
start (e.g., on startup or when the user modifies settings).
    default: ``on``

Cloud
-----

The term ``cloud`` refers to a (Pithos+) account on a Synnefo deployment and is used by the client (a) for authentication and (b) to retrieve endpoint information.

Agkyra requires just a couple of cloud settings to authenticate the user:

:dfn:`url` The authentication URL of the Synnefo deployment, which can be used by the client to retrieve the rest of the accessible API endpoints

:dfn:`token` The user authentication token

.. note:: To get the ``authentication URL`` (and ``token``), browse to the main page of the cloud, log in, click the username (e-mail) on the upper right corner and click API access.

Each ``cloud`` is given a name, so that multiple clouds can be configured in the same setup. In case of multiple clouds, the user can manage them only through the :ref:`cli` (or by editing the `$agkyra_dir/config.rc` file). If the settings are provided through the GUI, a cloud name will be generated automatically.

Sync
----

The term ``sync`` refers to a pair of a local ``directory`` and a remote ``container``. The container is located in a ``cloud`` (aka a specific user account on a Pithos+ service).

:dfn:`directory` The **full path** of the local directory (e.g. `/home/user/data` in unix-like enviroments)

:dfn:`container` The remote container (e.g. `images` or `pithos`)

:dfn:`cloud` The name of the (previously defined) ``cloud``, where the container is located

.. note:: If you don't know what a container is and you just want to synchronize the contents of the remote storage to your local directory, try `pithos` as a container value

Each ``sync`` is given a name, so that multiple syncs can be configured in the same setup. In case of multiple syncs, the user can manage them only through the :ref:`cli` (or by editing the `$agkyra_dir/config.rc` file). If the settings are provided through the GUI, a sync name will be generated automatically.
