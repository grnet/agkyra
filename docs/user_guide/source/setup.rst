Installation
============

There are packages to easily install and run the application in all major
platforms. There is also the option for downloading the source code and
installing everything manually.

Linux
-----

TODO

Windows
-------

TODO

Mac OS X
--------

TODO

Install from source
-------------------

Essential Requirements:

* `Python 2.7 <https://www.python.org/downloads/>`_
* setuptools_

GUI requirements:

* nwjs_

.. note:: If the nwjs_ installation is skipped, the GUI won't function, but the
    CLI will

When the essential requirements are installed, use setuptools to download and
install the agkyra package. It contains a back-end, a UI helper, a CLI and a
GUI.

.. code-block:: console

    $ pip install agkyra

.. hint:: if `pip install` does not work in windows, try `easy_setup`

To install the GUI, download the latest stable nwjs_ build and move it to the
agkyra source directory.

.. code-block:: console

    $ wget http://dl.nwjs.io/v0.12.3/nwjs-v0.12.3-YOUR_OS-x32OR64.tar.gz
    $ tar xvfz nwjs-v0.12.3-YOUR_OS-x32OR64.tar.gz
    $ mv nwjs `$AGKYRA_SOURCE/agkyra/nwjs

TODO: Different names between operating systems

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

Use the **agkyra-cli config** commands to set and update settings:

.. code-block:: console

    --- Set up a cloud named CLD ---
    $ agkyra-cli config set cloud CLD url http://www.example.org/identity/v2.0
    $ agkyra-cli config set cloud CLD token ex4mpl3-t0k3n

    --- Set up a sync (cloud, local directory, container) named SNC ---
    $ agkyra-cli config set sync SNC directory /my/local/directory
    $ agkyra-cli config set sync SNC cloud CLD
    $ agkyra-cli config set sync SNC container remote_container

    --- Set the SNC sync as the default ---
    $ agkyra-cli config set default_sync CLD


.. note:: use the **agkyra-cli config list** command for the current settings


Config file
-----------

The config file is `HOME_DIRECTORY/.agkyra/config.rc` and can be edited,
although this practice is discouraged. The config file format is modeled after
the corresponding `kamaki.rc` format.

Here is a typical configuration:

.. code-block:: text

    # Agkyra configuration file version 0.2
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

.. _Python: http://www.python.org
.. _setuptools: https://pypi.python.org/pypi/setuptools/
.. _nwjs: http://nwjs.io/
