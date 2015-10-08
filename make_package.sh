#!/usr/bin/env bash
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

ID=agkyra-$(date +%s)
BUILDDIR=$CURPWD/build/$ID
echo building under $BUILDDIR
DISTDIR=$CURPWD/dist
TMPAGKYRA=$BUILDDIR/agkyra
mkdir -p $TMPAGKYRA
WHEELHOUSE=$TMPAGKYRA/wheelhouse

pip wheel . -w $WHEELHOUSE
if [ $? -ne 0 ]; then
    exit 1
fi

cd $WHEELHOUSE
for i in *; do unzip $i -d $TMPAGKYRA/lib; done
cd $TMPAGKYRA
rm -r $WHEELHOUSE

cp $ROOTPATH/agkyra/scripts/agkyra $TMPAGKYRA/agkyra
rm -r $DISTDIR/agkyra

mv $TMPAGKYRA $DISTDIR
echo built in $DISTDIR/agkyra
