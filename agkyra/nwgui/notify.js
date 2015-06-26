var gui = require('nw.gui');

var NOTIFICATION = {
    0: 'Not initialized',
    1: 'Initializing ...',
    2: 'Shutting down',
    100: 'Syncing',
    101: 'Pausing',
    102: 'Paused',
    200: 'Settings are incomplete',
    201: 'Cloud URL error',
    202: 'Authentication error',
    203: 'Local directory error',
    204: 'Remote container error',
    1000: 'error error'
}

function is_up(code) { return (code / 100 >> 0) === 1; }
function has_settings_error(code) { return (code / 200 >> 0) === 2; }
function remaining(status) { return status.unsynced - status.synced; }

var ntf_title = {
    'info': 'Agkyra Notification',
    'warning': 'Agkyra Warning',
    'error': 'Agkyra Error'
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

function notify_user(msg, level) {
    var n = new Notification(ntf_title[level], {
        lang: 'utf-8', body: msg, icon: ntf_icon[level]
    });
    setTimeout(n.close.bind(n), ntf_timeout[level]);
}