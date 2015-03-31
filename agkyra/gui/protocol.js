var gui = require('nw.gui');
var path = require('path');

// Read config file
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
    'pithos_url': null,
    'weblogin': null,
    'exclude': null
  },
  'status': {"progress": null, "paused": null}
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
  console.log('SEND post pause');
  send_json(socket, {'method': 'post', 'path': 'pause'});
} // expected response: {"OK": 200}

function post_start(socket) {
  console.log('SEND post start');
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
} // expected response {"progress": ..., "paused": ...}


// Connect to helper
var socket = new WebSocket(cnf['address']);
socket.onopen = function() {
  console.log('Send GUI ID to helper');
  post_gui_id(this);
}
socket.onmessage = function(e) {
  var r = JSON.parse(e.data)
  //console.log('RECV: ' + r['action'])
  switch(r['action']) {
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
    console.log('Connection to helper closed');
    closeWindows();
}
