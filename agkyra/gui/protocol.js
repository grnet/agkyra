var gui = require('nw.gui');

// Read config file
var fs = require('fs');
var cnf = JSON.parse(fs.readFileSync(gui.App.argv[0], encoding='utf-8'));

setTimeout(function() {
  // Connect to helper
  var socket = new WebSocket('ws://localhost:' + cnf['port']);
  socket.onopen = function() {
    console.log('Connecting to helper');
    this.send(cnf['token']);
  }
  socket.onmessage = function(e) {
    console.log('message', e.data);
  };
  socket.onerror = function () {
      console.log('GUI and helper cannot communicate, quiting');
      gui.Window.get().close();
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
    tooltip: 'Paused (0% synced)',
    title: 'Agkyra syncs with Pithos+',
    icon: 'icons/tray.png'
  });

  var menu = new gui.Menu();

  // See contents
  menu.append(new gui.MenuItem({type: 'separator'}));
  menu.append(new gui.MenuItem({
    label: 'Open local folder',
    icon: 'icons/folder.png',
    click: function () {gui.Shell.showItemInFolder('.');}
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
    click: function () {
      console.log('Exiting client');
      console.log('Exiting GUI');
      closeWindows()
    }
  }));

  tray.menu = menu;
}, 100); // Timeout in milliseconds
