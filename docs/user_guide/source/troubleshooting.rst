Troubleshooting
===============

Agkyra hanged up expectingly
----------------------------

Maybe it's just the GUI.

The GUI is a separate component (it is even developed in a different
programming language to the rest of the application). Use the command line to
check if the application is still running:

.. code-block: console

    $ agkyra cli status

If the status is ``Syncing``, ``Pausing`` or ``Paused``, then the application
is running. Try running agkyra again and see if everything is OK.

Otherwise, see the next issue.

Agkyra is not starting
----------------------

The application has to be reset manually. We can do this without data loss.
You need to remove the session locks to enable the application to start again.
To do that, remove the files ``$agkyra_dir/session.db`` and
``agkyra_dir/session.info``.

.. note:: To check the exact value of ``agkyra_dir``

    .. code-block:: console

        $ agkyra cli config list global agkyra_dir

Agkyra is still not starting
----------------------------

Probably the helper (scripts/server.py) is in stale. Find the process and kill
it, e.g.:

.. code-block:: console

    --- in unix-like enviroments ---
    $ ps aux|grep server.py
    user 1234 ... ... python /home/user/agkyra/scripts/server.py
    $ kill -9 1234

I still have problems
---------------------

Please, contact us at TODO
