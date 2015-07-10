// Copyright (C) 2015 GRNET S.A.
//
// This program is free software: you can redistribute it and/or modify
// it under the terms of the GNU General Public License as published by
// the Free Software Foundation, either version 3 of the License, or
// (at your option) any later version.
//
// This program is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
// GNU General Public License for more details.
//
// You should have received a copy of the GNU General Public License
// along with this program.  If not, see <http://www.gnu.org/licenses/>.

var gui = require('nw.gui');

function is_up(code) { return (code / 100 >> 0) === 1; }
function has_settings_error(code) { return (code / 200 >> 0) === 2; }
function remaining(status) {
    return status.unsynced - (status.synced + status.failed);
}

var ntf_icon = {
    'info': 'static/images/ntf_info.png',
    'warning': 'static/images/ntf_warning.png',
    'error': 'static/images/ntf_error.png',
}

var ntf_timeout = {
    'info': 1000,
    'warning': 1500,
    'error': 4000
}

var notify_menu = new gui.MenuItem({
    label: 'Notifications',
    icon: 'static/images/play_pause.png',
    iconIsTemplate: false,
});

function notify_user(msg, level, ntf_title) {
    var n = new Notification(ntf_title[level], {
        lang: 'utf-8', body: msg, icon: ntf_icon[level]
    });
    setTimeout(n.close.bind(n), ntf_timeout[level]);
}