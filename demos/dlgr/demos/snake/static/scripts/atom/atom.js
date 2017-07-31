(function() {
  var Game, atom, c, eventCode, requestAnimationFrame,
    __indexOf = Array.prototype.indexOf || function(item) { for (var i = 0, l = this.length; i < l; i++) { if (i in this && this[i] === item) return i; } return -1; };

  requestAnimationFrame = window.requestAnimationFrame || window.webkitRequestAnimationFrame || window.mozRequestAnimationFrame || window.oRequestAnimationFrame || window.msRequestAnimationFrame || function(callback) {
    return window.setTimeout((function() {
      return callback(1000 / 60);
    }), 1000 / 60);
  };

  window.atom = atom = {};

  atom.input = {
    _bindings: {},
    _down: {},
    _pressed: {},
    _released: [],
    mouse: {
      x: 0,
      y: 0
    },
    bind: function(key, action) {
      return this._bindings[key] = action;
    },
    onkeydown: function(e) {
      var action;
      action = this._bindings[eventCode(e)];
      if (!action) return;
      if (!this._down[action]) this._pressed[action] = true;
      this._down[action] = true;
      e.stopPropagation();
      return e.preventDefault();
    },
    onkeyup: function(e) {
      var action;
      action = this._bindings[eventCode(e)];
      if (!action) return;
      this._released.push(action);
      e.stopPropagation();
      return e.preventDefault();
    },
    clearPressed: function() {
      var action, _i, _len, _ref;
      _ref = this._released;
      for (_i = 0, _len = _ref.length; _i < _len; _i++) {
        action = _ref[_i];
        this._down[action] = false;
      }
      this._released = [];
      return this._pressed = {};
    },
    pressed: function(action) {
      return this._pressed[action];
    },
    down: function(action) {
      return this._down[action];
    },
    released: function(action) {
      return __indexOf.call(this._released, action) >= 0;
    },
    onmousemove: function(e) {
      var b, d, ev;
      if (window.pageXOffset !== void 0) {
        this.mouse.x = e.clientX + window.pageXOffset;
        return this.mouse.y = e.clientY + window.pageYOffset;
      } else {
        ev = window.event;
        d = document.documentElement;
        b = document.body;
        this.mouse.x = ev.clientX + d.scrollLeft + b.scrollLeft;
        return this.mouse.y = ev.clientY + d.scrollTop + b.scrollTop;
      }
    },
    onmousedown: function(e) {
      return this.onkeydown(e);
    },
    onmouseup: function(e) {
      return this.onkeyup(e);
    },
    onmousewheel: function(e) {
      this.onkeydown(e);
      return this.onkeyup(e);
    },
    oncontextmenu: function(e) {
      if (this._bindings[atom.button.RIGHT]) {
        e.stopPropagation();
        return e.preventDefault();
      }
    }
  };

  document.onkeydown = atom.input.onkeydown.bind(atom.input);

  document.onkeyup = atom.input.onkeyup.bind(atom.input);

  document.onmouseup = atom.input.onmouseup.bind(atom.input);

  atom.button = {
    LEFT: -1,
    MIDDLE: -2,
    RIGHT: -3,
    WHEELDOWN: -4,
    WHEELUP: -5
  };

  atom.key = {
    TAB: 9,
    ENTER: 13,
    ESC: 27,
    SPACE: 32,
    LEFT_ARROW: 37,
    UP_ARROW: 38,
    RIGHT_ARROW: 39,
    DOWN_ARROW: 40
  };

  for (c = 65; c <= 90; c++) {
    atom.key[String.fromCharCode(c)] = c;
  }

  eventCode = function(e) {
    if (e.type === 'keydown' || e.type === 'keyup') {
      return e.keyCode;
    } else if (e.type === 'mousedown' || e.type === 'mouseup') {
      switch (e.button) {
        case 0:
          return atom.button.LEFT;
        case 1:
          return atom.button.MIDDLE;
        case 2:
          return atom.button.RIGHT;
      }
    } else if (e.type === 'mousewheel') {
      if (e.wheel > 0) {
        return atom.button.WHEELUP;
      } else {
        return atom.button.WHEELDOWN;
      }
    }
  };

  atom.canvas = document.getElementsByTagName('canvas')[0];

  atom.canvas.style.position = "absolute";

  atom.canvas.style.top = "0";

  atom.canvas.style.left = "0";

  atom.context = atom.canvas.getContext('2d');

  atom.canvas.onmousemove = atom.input.onmousemove.bind(atom.input);

  atom.canvas.onmousedown = atom.input.onmousedown.bind(atom.input);

  atom.canvas.onmouseup = atom.input.onmouseup.bind(atom.input);

  atom.canvas.onmousewheel = atom.input.onmousewheel.bind(atom.input);

  atom.canvas.oncontextmenu = atom.input.oncontextmenu.bind(atom.input);

  window.onresize = function(e) {
    atom.canvas.width = window.innerWidth;
    atom.canvas.height = window.innerHeight;
    atom.width = atom.canvas.width;
    return atom.height = atom.canvas.height;
  };

  window.onresize();

  Game = (function() {

    function Game() {}

    Game.prototype.update = function(dt) {};

    Game.prototype.draw = function() {};

    Game.prototype.run = function() {
      var s,
        _this = this;
      if (this.running) return;
      this.running = true;
      s = function() {
        if (!_this.running) return;
        _this.step();
        return requestAnimationFrame(s);
      };
      this.last_step = Date.now();
      return requestAnimationFrame(s);
    };

    Game.prototype.stop = function() {
      return this.running = false;
    };

    Game.prototype.step = function() {
      var dt, now;
      now = Date.now();
      dt = (now - this.last_step) / 1000;
      this.last_step = now;
      this.update(dt);
      this.draw();
      return atom.input.clearPressed();
    };

    return Game;

  })();

  atom.Game = Game;

}).call(this);
