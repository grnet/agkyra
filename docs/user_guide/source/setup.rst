.. _installation:

Installation
============

There are packages to easily install and run the application in all major
platforms. You can download them from the `Agkyra home page`_.

Linux
-----

Untar the agkyra package and run the executable `agkyra`.

Windows
-------

Unzip the agkyra package and double-click the executable `agkyra.exe`.

Mac OS X
--------

Unzip the agkyra package and double-click the app `Agkyra.app`.

.. _setup:

Setup
=====

Some essential settings must be provided in order for Agkyra to start syncing:

* A synnefo cloud URL
* A user authentication token
* A remote container (if it does not exist, it will be created)
* A local directory (if it does not exist, it will be created)

.. note:: The full list of settings is detailed in the settings section

If any of the above is missing or is outdated, agkyra will not be able to
function properly. There are several ways to provide and update these settings

GUI
---

Start agkyra (in GUI mode by default). If some of the required settings are
missing, or the token fails to authenticate, the `Settings` window will pop up.
Otherwise, click the tray icon and choose "Settings".

In the `Settings` window:

* The **cloud URL** must be provided manually.
* To get the **user token**, click the "Login to retrieve token" to authenticate with a username and password. It has to be re-retrieved every time it expires or is invalidated in any other way.
* Write the **container** name in the corresponding field. If the container does not exist, it will be created automatically, otherwise the contained data will be preserved and synchronized.
* Select the **local directory** by clicking the `Select` button and using the pop up dialog.

To apply the settings, press the `Save` button. If the Settings window is
closed without saving, all changes will be lost.

CLI
---

Use the **agkyra config** commands to set and update settings:

.. code-block:: console

    --- Set up a cloud named CLD ---
    $ agkyra config set cloud CLD url http://www.example.org/identity/v2.0
    $ agkyra config set cloud CLD token ex4mpl3-t0k3n

    --- Set up a sync (cloud, local directory, container) named SNC ---
    $ agkyra config set sync SNC directory /my/local/directory
    $ agkyra config set sync SNC cloud CLD
    $ agkyra config set sync SNC container remote_container

    --- Set the SNC sync as the default ---
    $ agkyra config set default_sync CLD


.. note:: use the **agkyra config list** command for the current settings


Config file
-----------

The config file is `HOME_DIRECTORY/.agkyra/config.rc` and can be edited,
although this practice is discouraged. The config file format is modeled after
the corresponding `kamaki.rc` format.

Here is a typical configuration:

.. code-block:: text

    # Agkyra configuration file version XXX
    [global]
    default_sync = CLD
    language = en
    sync_on_start = on

    [cloud "CLD"]
    url = http://www.example.org/identity/v2.0
    token = ex4mpl3-t0k3n

    [sync "SNC"]
    directory = /my/local/directory
    container = agkyra
    cloud = CLD

Users can create as many clouds and syncs as they like, but only the
`default_sync` cloud is running each time `agkyra` is launched.

.. External links

.. _Agkyra home page: https://www.synnefo.org/agkyra/
