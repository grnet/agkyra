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

VERSION="v0.12.3"

CURPWD=$(pwd)
cd "$(dirname "$0")"
ROOTDIR=$(pwd)

declare -A nwjsfile
nwjsfile[win64]="nwjs-${VERSION}-win-x64.zip"
nwjsfile[osx64]="nwjs-${VERSION}-osx-x64.zip"
nwjsfile[linux64]="nwjs-${VERSION}-linux-x64.tar.gz"
nwjsfile[win32]="nwjs-${VERSION}-win-ia32.zip"
nwjsfile[osx32]="nwjs-${VERSION}-osx-ia32.zip"
nwjsfile[linux32]="nwjs-${VERSION}-linux-ia32.tar.gz"

if [[ -z $1 ]]; then
    echo "Select one of:" ${!nwjsfile[@]}
    exit 1
fi

os=$1
file=${nwjsfile[$os]}
url="http://dl.nwjs.io/${VERSION}/"$file

echo "Will first download nwjs."
AGKPATH=agkyra
NWJSPATH=$AGKPATH/nwjs
if [ -d $NWJSPATH ]; then
    echo "Warning: cleaning up $NWJSPATH."
    rm -r $NWJSPATH
fi

mkdir $NWJSPATH
wget $url
if [[ "$os" =~ ^(linux64|linux32)$ ]]; then
    tar xzf $file --strip-components 1 -C $NWJSPATH
else
    unzip -d tmpnwjs $file && mv tmpnwjs/*/* $NWJSPATH && rm -r tmpnwjs
fi

rm $file
