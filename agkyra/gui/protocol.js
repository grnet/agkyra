var gui = require('nw.gui');
var path = require('path');

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
    'pithos_url': null,
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
  closeWindows();
} // expected response: nothing

function post_pause(socket) {
  console.log('SEND post pause');
  requests.push('post pause');
  send_json(socket, {'method': 'post', 'path': 'pause'});
} // expected response: {"OK": 200}

function post_start(socket) {
  console.log('SEND post start');
  requests.push('post start');
  send_json(socket, {'method': 'post', 'path': 'start'});
} // expected response: {"OK": 200}

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
      if (r['ACCEPTED'] === 202) {
        get_settings(this);
        get_status(this);
      } else {
        console.log('Helper: ' + JSON.stringify(r));
        closeWindows();
      }
    break;
    case 'post start':
    case 'post pause': console.log('RECV ' + r['OK']);
      if (r['OK'] === 200) {
        get_status(this);
      } else {
        console.log('Helper: ' + JSON.stringify(r));
      }
    break;
    case 'get settings':
      console.log(r);
      globals['settings'] = r;
    break;
    case 'put settings':
      if (r['CREATED'] === 201) {
        get_settings(this);
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

// Progress and Pause
var start_syncing = 'Start syncing';
var pause_syncing = 'Pause syncing';
var paused = true;

progress_item = new gui.MenuItem({
  // progress menu item
  label: 'Initializing',
  type: 'normal'
});
menu.append(progress_item);
pause_item = new gui.MenuItem({
  // pause menu item
  label: '',
  type: 'normal',
  click: function() {
    if(paused) {post_start(socket);}
    else {post_pause(socket);}
  }
});
pause_item.enabled = false;
menu.append(pause_item);

// Update progress

function reset_status() {
  var status = globals['status'];
  var new_progress = progress_item.label;
  var new_pause = pause_item.label;
  var menu_modified = false;
  if (status['paused'] !== null) {
    switch(pause_item.label) {
      case pause_syncing: if (status['paused']) {
          // Update to "Paused - start syncing"
          paused = true;
          new_pause = start_syncing;
          progress_item.enabled = false;
          menu_modified = true;
        } // else continue syncing
        new_progress = 'Progress: ' + status['progress'] + '%';
      break;
      case start_syncing: if (status['paused']) return;
        // else update to "Syncing - pause syncing"
        paused = false;
        new_pause = pause_syncing;
        progress_item.enabled = true;
        new_progress = 'Progress: ' + status['progress'] + '%';
        menu_modified = true;
      break;
      default:
        if (status['paused']) {new_pause = start_syncing; paused=true;}
        else {new_pause = pause_syncing; paused=false;}
        new_progress = 'Progress: ' + status['progress'] + '%';
        pause_item.enabled = true;
        progress_item.enabled = true;
        menu_modified = true;
    }
  }
  if (new_pause != pause_item.label) {
    pause_item.label = new_pause;
    menu_modified = true;
  }
  if (new_progress != progress_item.label) {
    progress_item.label = new_progress;
    menu_modified = true;
  }
  if (menu_modified) tray.menu = menu;
  get_status(socket);
}
window.setInterval(reset_status, 1000);

// Menu actions contents
menu.append(new gui.MenuItem({type: 'separator'}));
menu.append(new gui.MenuItem({
  label: 'Open local folder',
  icon: 'icons/folder.png',
  click: function () {
    var dir = globals['settings']['directory'];
    console.log('Open ' + dir);
    gui.Shell.showItemInFolder(dir);
  }
}));

menu.append(new gui.MenuItem({
  label: 'Launch Pithos+ page',
  icon: 'icons/pithos.png',
  click: function () {
    var pithos_url = globals['settings']['pithos_url'];
    console.log('Visit ' + pithos_url);
    gui.Shell.openExternal(pithos_url);
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
