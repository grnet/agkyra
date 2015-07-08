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

var DEBUG = true;

var gui = require('nw.gui');
var path = require('path');
var fs = require('fs');

// Read config file
var cnf = JSON.parse(fs.readFileSync(gui.App.argv[0], encoding='utf-8'));
var COMMON = JSON.parse(fs.readFileSync(path.join('..', 'ui_data/common_en.json')));

var STATUS = COMMON['STATUS'];

function log_debug(msg) { if (DEBUG) console.log(msg); }

function send_json(socket, msg) {
  socket.send(JSON.stringify(msg));
}

var globals = {
  settings: {
    token: null,
    url: null,
    container: null,
    directory: null,
    exclude: null,
    language: 'en',
    sync_on_start: true
  },
  status: {synced: 0, unsynced: 0, failed: 0, code: STATUS['UNINITIALIZED']},
  authenticated: false,
  open_settings: false,
  settings_are_open: false,
  notification: STATUS['UNINITIALIZED']
}

// Protocol: requests ::: responses
function post_ui_id(socket) {
  send_json(socket, {"method": "post", "ui_id": cnf['ui_id']})
} // expected response: {"ACCEPTED": 202}

function post_shutdown(socket) {
  send_json(socket, {'method': 'post', 'path': 'shutdown'});
  log_debug('Close all windows');
  closeWindows();
  log_debug('Close socket');
  socket.close();
  log_debug('Shutdown is complete');
} // expected response: nothing

function post_pause(socket) {
  log_debug('SEND post pause');
  send_json(socket, {'method': 'post', 'path': 'pause'});
} // expected response: {"OK": 200}

function post_start(socket) {
  log_debug('SEND post start');
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
} // expected response {"synced":.., "unsynced":.., "failed":..., code":..}


// Connect to helper
var socket = new WebSocket(cnf['address']);
socket.onopen = function() {
  log_debug('Send GUI ID to helper');
  post_ui_id(this);
}
socket.onmessage = function(e) {
  var r = JSON.parse(e.data)
  log_debug('RECV: ' + r['action'])
  if (globals.authenticated && r['UNAUTHORIZED'] === 401) {
    log_debug('Authentication error (wrong token?)');
    globals.open_settings = true;
    return
  }

  switch(r['action']) {
    case 'post ui_id':
      if (r['ACCEPTED'] === 202) {
        get_settings(this);
        get_status(this);
        globals.authenticated = true;
      } else {
        log_debug('Helper: ' + JSON.stringify(r));
        closeWindows();
      }
    break;
    case 'post start':
    case 'post pause':
      log_debug('RECV ' + r['OK']);
      if (r['OK'] === 200) {
        get_status(this);
      } else {
        log_debug('Helper: ' + JSON.stringify(r));
      }
    break;
    case 'get settings':
      log_debug(r);
      globals['settings'] = r;
    break;
    case 'put settings':
      if (r['CREATED'] === 201) {
        get_settings(this);
      } else {
        log_debug('Helper: ' + JSON.stringify(r));
      }
    break;
    case 'get status':
      globals['status'] = r;
      if (!globals.open_settings)
        globals.open_settings = has_settings_error(r.code);
    break;
    default:
      console.log('Incomprehensible response ' + JSON.stringify(r));
  }

};
socket.onerror = function (e) {
    console.log('GUI - helper error' + e.data);
    closeWindows();
}
socket.onclose = function() {
    log_debug('Connection to helper closed');
    closeWindows();
}
