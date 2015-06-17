var gui = require('nw.gui');

var ntf_title = {
    'info': 'Notification',
    'warning': 'Warning',
    'critical': 'Critical Error'
}
var ntf_icon = {
    'info': 'static/images/ntf_info.png',
    'warning': 'static/images/ntf_warning.png',
    'critical': 'static/images/ntf_critical.png',
}

var notify_menu = new gui.MenuItem({
    label: 'Notifications',
    icon: 'static/images/play_pause.png',
    iconIsTemplate: false,
    click: function() {
        console.log('Notification is clecked');
    }
});

function notify_user(msg, level) {
    var n = new Notification(ntf_title[level], {
        lang: 'utf-8',
        body: msg,
        icon: ntf_icon[level]
    });
    setTimeout(n.close.bind(n), 4000);
}