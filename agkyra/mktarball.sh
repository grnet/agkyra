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

declare -A nwjsfile
nwjsfile[win64]="nwjs-v0.12.1-win-x64.zip"
nwjsfile[osx64]="nwjs-v0.12.1-osx-x64.zip"
nwjsfile[linux64]="nwjs-v0.12.1-linux-x64.tar.gz"
nwjsfile[win32]="nwjs-v0.12.1-win-ia32.zip"
nwjsfile[osx32]="nwjs-v0.12.1-osx-ia32.zip"
nwjsfile[linux32]="nwjs-v0.12.1-linux-ia32.tar.gz"

if [[ -z $1 ]]; then
    echo "Select one of:" ${!nwjsfile[@]}
    exit
fi

ID=agkyra-$(date +%s)
TMPDIR=/tmp/$ID
TMPAGKYRA=$TMPDIR/agkyra
mkdir -p $TMPAGKYRA

cp launch $TMPAGKYRA
cp README.md $TMPAGKYRA
cp COPYING $TMPAGKYRA
git ls-files agkyra | xargs cp --parents -t $TMPAGKYRA

cd $TMPAGKYRA/agkyra/gui
zip -r ../gui.nw .
cd .. && rm -r gui

os=$1
file=${nwjsfile[$os]}
url="http://dl.nwjs.io/v0.12.1/"$file

cd $TMPAGKYRA/agkyra
wget $url
if [[ "$os" =~ ^(linux64|linux32)$ ]]; then
    mkdir nwjs
    tar xzf $file --strip-components 1 -C nwjs
else
    unzip -d nwjs "$file" && f=(nwjs/*) && mv nwjs/*/* nwjs && rmdir "${f[@]}"
fi

rm $file

cd $TMPDIR
tar czf $CURPWD/agkyra-snapshot-${os}.tar.gz agkyra
