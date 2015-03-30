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
