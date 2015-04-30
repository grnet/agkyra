var gui = require('nw.gui');
var path = require('path');

// Read config file
var DEBUG = false;
var fs = require('fs');
var cnf = JSON.parse(fs.readFileSync(gui.App.argv[0], encoding='utf-8'));
fs.writeFile(gui.App.argv[0], 'consumed');

function send_json(socket, msg) {
  socket.send(JSON.stringify(msg))
}

var globals = {
  'settings': {
    'token': null,
    'url': null,
    'container': null,
    'directory': null,
    'exclude': null
  },
  'status': {"synced": 0, "unsynced": 0, "paused": null, "can_sync": false},
  'authenticated': false,
}

// Protocol: requests ::: responses
function post_gui_id(socket) {
  send_json(socket, {"method": "post", "gui_id": cnf['gui_id']})
} // expected response: {"ACCEPTED": 202}

function post_shutdown(socket) {
  send_json(socket, {'method': 'post', 'path': 'shutdown'});
  closeWindows();
} // expected response: nothing

function post_pause(socket) {
  if (DEBUG) console.log('SEND post pause');
  send_json(socket, {'method': 'post', 'path': 'pause'});
} // expected response: {"OK": 200}

function post_start(socket) {
  if (DEBUG) console.log('SEND post start');
  send_json(socket, {'method': 'post', 'path': 'start'});
} // expected response: {"OK": 200}

function get_settings(socket) {
  send_json(socket, {'method': 'get', 'path': 'settings'});
} // expected response: {settings JSON}

function put_settings(socket, new_settings) {
  new_settings['method'] = 'put';
  new_settings['path'] = 'settings';
  send_json(socket, new_settings);
} // expected response: {"CREATED": 201}

function get_status(socket) {
  send_json(socket, {'method': 'get', 'path': 'status'});
} // expected response {"synced":.., "unsynced":.., "paused":.., "can_sync":..}


// Connect to helper
var socket = new WebSocket(cnf['address']);
socket.onopen = function() {
  if (DEBUG) console.log('Send GUI ID to helper');
  post_gui_id(this);
}
socket.onmessage = function(e) {
  var r = JSON.parse(e.data)
  if (DEBUG) console.log('RECV: ' + r['action'])
  switch(r['action']) {
    case 'post gui_id':
      if (r['ACCEPTED'] === 202) {
        get_settings(this);
        get_status(this);
        globals.authenticated = true;
      } else {
        if (DEBUG) console.log('Helper: ' + JSON.stringify(r));
        closeWindows();
      }
    break;
    case 'post start':
    case 'post pause':
      if (DEBUG) console.log('RECV ' + r['OK']);
      if (r['OK'] === 200) {
        get_status(this);
      } else {
        if (DEBUG) console.log('Helper: ' + JSON.stringify(r));
      }
    break;
    case 'get settings':
      if (DEBUG) console.log(r);
      globals['settings'] = r;
    break;
    case 'put settings':
      if (r['CREATED'] === 201) {
        get_settings(this);
      } else {
        if (DEBUG) console.log('Helper: ' + JSON.stringify(r));
      }
    break;
    case 'get status':
      globals['status'] = r;
    break;
    default:
      console.log('Incomprehensible response ' + r);
  }

};
socket.onerror = function (e) {
    console.log('GUI - helper error' + e.data);
    closeWindows();
}
socket.onclose = function() {
    if (DEBUG) console.log('Connection to helper closed');
    closeWindows();
}
