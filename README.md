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

### Packaging

A package for Windows, OSX and Linux, that fully contains dependencies and
the Python framework can be created with PyInstaller.

1. Run `pip install pyinstaller`.

* Note: On Linux, we currently need the development version 3.0.dev2 of
  PyInstaller.
  Get the code from `https://github.com/pyinstaller/pyinstaller`. No
  installation is needed: `pyinstaller.py` can directly run from the repo's
  root directory.

* Note: On Windows, PyWin32 is a prerequisite. Visit
  `http://sourceforge.net/projects/pywin32/files/` and pick the appropriate
  version for your Python installation.

2. Run `pyinstaller agkyra.spec`. This will make the application under
   `dist/agkyra` (and `dist/agkyra.app` under OSX).

* The sqlite3 version 3.8.5 that comes with Mac OS X 10.10 does not
  work properly. You can build agkyra with a newer sqlite3
  library. Assuming you have installed one (eg with brew) under
  `/usr/local/opt/sqlite`, you need to build with environment variable
  `DYLD_LIBRARY_PATH=/usr/local/opt/sqlite/lib`. Then go to
  `dist/agkyra.app/Contents/MacOS` and run `install_name_tool -change
  '/usr/lib/libsqlite3.dylib' '@loader_path/libsqlite3.dylib'
  _sqlite3.so`

3. Make an archive (zip, or gzipped tar) with `python bundle.py <platform>`.

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
