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

/**
* Methods for accessing settings between documents
*/

function export_settings(settings) {
    global.settings = settings;
}

function import_settings() {
    return global.settings;
}

function get_setting(key) {
    return global.settings[key];
}

function get_dialogue() {
    return global.dialogue;
}

function set_setting(key, val) {
    global.settings[key] = val;
}

function set_dialogue(msg, terms, response) {
    global.dialogue = {msg: msg, terms: terms, response: response};
}

function refresh_endpoints(identity_url) {
    $.post(identity_url + '/tokens', function(data) {
        var endpoints = data.access.serviceCatalog;
        global.url_error = global.url_error || null;
        $.each(endpoints, function(i, endpoint) {
            switch(endpoint.type) {
            case 'object-store': try {
                global.pithos_ui = null;
                global.pithos_ui = endpoint['endpoints'][0]['SNF:uiURL'];
            } catch(err) { console.log('Failed to get pithos_ui ' + err); }
            break;
            case 'account': try {
                global.account_ui = null;
                global.account_ui = endpoint['endpoints'][0]['SNF:uiURL'];
            } catch(err) { console.log('Failed to get account_ui ' + err); }
            break;
            }
        });
    }).fail(function(xhr, status, msg) {
        global.url_error = xhr.status + ' ' + msg;
        console.log(xhr.status + ' ' + xhr.responseText);
    });
}

function check_auth(identity_url, token) {
    var data2send = {auth: {token: {id: token}}};
    $.ajax({
        type: 'POST', url: identity_url + '/tokens',
        beforeSend: function(req) {
            req.setRequestHeader('X-Auth-Token', token);
        },
        headers: {
            'Content-Type': 'application/json'
        },
        data: JSON.stringify(data2send),
        dataType: 'json'
    })
    .done(function() {global.auth_error = null;})
    .fail(function(xhr, status, msg) {
        global.auth_error = xhr.status + ' ' + msg;
        console.log(xhr.status + ' ' + xhr.responseText);
    });
}

function get_pithos_ui() {return global.pithos_ui || null;}

function get_account_ui() {return global.account_ui || null;}

function get_url_error() {return global.url_error || null;}

function get_auth_error() {return global.auth_error || null;}