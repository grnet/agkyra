# Agkyra

## Overview

This is a syncing client for object storage.

## Installation and Packaging

This will help you to install `agkyra` from source.

### Prerequisites

You need to have Python 2.7 installed. If it is not provided by your
operating system, visit `https://www.python.org/downloads/`.

### Installation process

1. Run `python configure.py <platform>`. Paramater `platform` can be
   one of `win64, win32, osx64, osx32, linux64, linux32`. This will
   download `NW.js` and copy it into the source tree. It will also
   copy SSL certificate from `certifi` package.

2. Run `python setup.py install` (or `develop`).

* Note that on Windows with Python >=2.7.9 this may fail with an SSL
  verification error. If so, visit `https://pypi.python.org` with Internet
  Explorer. You will be prompted to accept the website's certificate. Do so
  and then retry step 2.

### Packaging for Windows

A package for Windows, that fully contains dependencies and the
Python framework, can be created with PyInstaller.

1. We currently need the development version 3.0.dev2 of PyInstaller. Get
   the code from `https://github.com/pyinstaller/pyinstaller` and `git
   checkout 3.0.dev2`. No installation is needed: `pyinstaller.py` can
   directly run from the repo's root directory.

* Note: On Windows, PyWin32 is a prerequisite. Visit
  `http://sourceforge.net/projects/pywin32/files/` and pick the
  appropriate version for your Python installation. If you run in a
  virtualenv, you can install PyWin32 by running `easy_install` on the
  downloaded setup executable.

2. Run `pyinstaller agkyra.spec`. This will make the application under
   `dist/agkyra`.

3. Make a zip archive with `python bundle.py <platform>`.

### Packaging for Linux and OSX

You can make a package for Linux and OSX, that contains dependencies
but not the standard Python libraries or the Python interpreter, using
a script based on `wheel`.

1. Run `pip install wheel`.

2. Run `make_package.sh`. This will make the application under
   `dist/agkyra`.

* The sqlite3 version that comes with Mac OS X >=10.10 does not
  work properly. You can build agkyra with a newer sqlite3
  library. Assuming you have installed one (eg with brew) under
  `/usr/local/opt/sqlite`, run `fix_sqlite_osx.sh
  /usr/local/opt/sqlite/lib/libsqlite3.dylib`.

3. On OSX, we can make an app with `platypus`. Get the tool from
`http://www.sveinbjorn.org/platypus` and install its command-line
version, too. Then run `mk_osx_app.sh`. The app is stored at
`dist/Agkyra.app`.

4. Make an archive (gzipped tar on Linux, zip on OSX) with `python
bundle.py <platform>`.

## Copyright and license

Copyright (C) 2015 GRNET S.A.

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
