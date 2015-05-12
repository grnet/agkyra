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

function set_setting(key, val) {
    global.settings[key] = val;
}

function refresh_endpoints(identity_url) {
    $.post(identity_url + '/tokens', function(data) {
        var endpoints = data.access.serviceCatalog
        global.pithos_ui = null;
        global.account_ui = null;
        $.each(endpoints, function(i, endpoint) {
            switch(endpoint.type) {
            case 'object-store': try {
                global.pithos_ui = endpoint['endpoints'][0]['SNF:uiURL'];
            } catch(err) { console.log('Failed to get pithos_ui ' + err); }
            break;
            case 'account': try {
                global.account_ui = endpoint['endpoints'][0]['SNF:uiURL'];
            } catch(err) { console.log('Failed to get account_ui ' + err); }
            break;
            }
        });
    });
}

function get_pithos_ui() {
    if (global.pithos_ui) {return global.pithos_ui;}
    else {return null;}
}

function get_account_ui() {
    if (global.account_ui) {return global.account_ui;}
    else {return null;}
}
