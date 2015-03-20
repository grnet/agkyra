var gui = require('nw.gui');

// Read config file
var fs = require('fs');
var cnf = JSON.parse(fs.readFileSync(gui.App.argv[0], encoding='utf-8'));
fs.writeFile(gui.App.argv[0], 'consumed');

function send_json(socket, msg) {
  socket.send(JSON.stringify(msg))
}

var requests = []
var globals = {
  'settings': {
    'token': null,
    'url': null,
    'container': null,
    'directory': null,
    'exclude': null
  },
  'status': {"progress": null, "paused": null}
}

// Protocol: requests ::: responses
function post_gui_id(socket) {
  requests.push('post gui_id');
  send_json(socket, {"method": "post", "gui_id": cnf['gui_id']})
} // expected response: {"ACCEPTED": 202}

function post_shutdown(socket) {
  send_json(socket, {'method': 'post', 'path': 'shutdown'});
} // expected response: nothing

function get_settings(socket) {
  requests.push('get settings');
  send_json(socket, {'method': 'get', 'path': 'settings'});
} // expected response: {settings JSON}

function put_settings(socket, new_settings) {
  requests.push('put settings');
  new_settings['method'] = 'put';
  new_settings['path'] = 'settings';
  send_json(socket, new_settings);
} // expected response: {"CREATED": 201}

function get_status(socket) {
  requests.push('get status');
  send_json(socket, {'method': 'get', 'path': 'status'});
} // expected response {"progress": ..., "paused": ...}


// Connect to helper
var socket = new WebSocket(cnf['address']);
socket.onopen = function() {
  console.log('Send GUI ID to helper');
  post_gui_id(this);
}
socket.onmessage = function(e) {
  var r = JSON.parse(e.data)
  switch(requests.shift()) {
    case 'post gui_id':
      if (r['ACCEPTED'] == 202) {
        get_settings(this);
        get_status(this);
      } else {
        console.log('Helper: ' + JSON.stringify(r));
        closeWindows();
      }
    break;
    case 'get settings':
      console.log(r);
      globals['settings'] = r;
    break;
    case 'put settings':
      if (r['CREATED'] == 201) {
        get_settings(socket);
      } else {
        console.log('Helper: ' + JSON.stringify(r));
      }
    break;
    case 'get status': globals['status'] = r;
    break;
    default:
      console.log('Incomprehensible response ' + r);
  }

};
socket.onerror = function (e) {
    console.log('GUI - helper error' + e.data);
    gui.Window.get().close();
}
socket.onclose = function() {
    console.log('Connection to helper closed');
    closeWindows();
}

// Setup GUI
var windows = {
  "settings": null,
  "about": null,
  "index": gui.Window.get()
}
function closeWindows() {
  for (win in windows) if (windows[win]) windows[win].close();
}

// GUI components
var tray = new gui.Tray({
  // tooltip: 'Paused (0% synced)',
  title: 'Agkyra syncs with Pithos+',
  icon: 'icons/tray.png'
});

var menu = new gui.Menu();


progress_menu = new gui.MenuItem({
  label: 'Calculating status',
  type: 'normal',
});
menu.append(progress_menu);
window.setInterval(function() {
  var status = globals['status']
  var msg = 'Syncing'
  if (status['paused']) msg = 'Paused'
  progress_menu.label = msg + ' (' + status['progress'] + '%)';
  tray.menu = menu;
  get_status(socket);
}, 5000);


// See contents
menu.append(new gui.MenuItem({type: 'separator'}));
menu.append(new gui.MenuItem({
  label: 'Open local folder',
  icon: 'icons/folder.png',
  click: function () {
    gui.Shell.showItemInFolder('.');
  }
}));

menu.append(new gui.MenuItem({
  label: 'Launch Pithos+ page',
  icon: 'icons/pithos.png',
  click: function () {
    gui.Shell.openExternal('https://pithos.okeanos.grnet.gr');
  }
}));

menu.append(new gui.MenuItem({
  label: 'Recently changed files',
  icon: 'icons/logs.png',
  click: function () {gui.Shell.openItem('logs.txt');}
}));

// Settings and About
menu.append(new gui.MenuItem({type: 'separator'}));
menu.append(new gui.MenuItem({
  label: 'Settings',
  icon: 'icons/settings.png',
  click: function () {
    if (windows['settings']) windows['settings'].close();
    windows['settings'] = gui.Window.open("settings.html", {
      "toolbar": false, "focus": true});
  }
}));

menu.append(new gui.MenuItem({
  label: 'About',
  icon: 'icons/about.png',
  click: function () {
    if (windows['about']) windows['about'].close();
    windows['about'] = gui.Window.open("about.html", {
      "toolbar": false, "resizable": false, "focus": true});
  }
}));

// Quit
menu.append(new gui.MenuItem({type: 'separator'}));
menu.append(new gui.MenuItem({
  label: 'Quit Agkyra',
  icon: 'icons/exit.png',
  click: function() {post_shutdown(socket);}
}));

tray.menu = menu;
