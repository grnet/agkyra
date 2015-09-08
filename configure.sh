#!/bin/bash
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

CURPWD=$(pwd)
cd "$(dirname "$0")"
ROOTPATH=$(pwd)

# this is needed for mock
pip install --upgrade setuptools

./get_nwjs.sh $1
if [ $? -ne 0 ]; then
    exit 1
fi

./cacert_cp.sh
if [ $? -ne 0 ]; then
    exit 1
fi

echo "Now run 'python setup.py install'."
