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

cd "$(dirname "$0")"
ROOTPATH=$(pwd)
DIST=$ROOTPATH/dist
LOGO=$DIST/agkyra/lib/agkyra/resources/nwgui/static/images/logo.icns
IDENT=org.synnefo.agkyra
VERSION=$(python -c "import agkyra; print agkyra.__version__")

platypus -a Agkyra -u 'GRNET S.A.' -o None -i $LOGO -Q $LOGO -p /usr/bin/env -V $VERSION -f $DIST/agkyra/lib -I $IDENT -B -R $DIST/agkyra/agkyra $DIST/Agkyra.app
