var gui = require('nw.gui');
var NOTIFIER = COMMON.NOTIFIER;

function is_up(code) { return (code / 100 >> 0) === 1; }
function has_settings_error(code) { return (code / 200 >> 0) === 2; }
function remaining(status) {
    return status.unsynced - (status.synced + status.failed);
}

var ntf_title = {
    'info': NOTIFIER.INFO,
    'warning': NOTIFIER.WARNING,
    'error': NOTIFIER.ERROR
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