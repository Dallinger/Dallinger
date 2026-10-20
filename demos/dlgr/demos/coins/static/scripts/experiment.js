/*globals $, dallinger */

// The game's rules, as in experiment.py. The page needs them to predict the
// player's moves.
var WIDTH = 20;
var HEIGHT = 12;
var SPEED = 5;
var REACH = 0.7;

var SCALE = 40;  // canvas pixels per unit of the arena
var COLORS = ['#d62728', '#1f77b4', '#2ca02c', '#9467bd'];

// Each player's sprite, one row of pixels per string
var SPRITES = [
  ['...XX...', '..XXXX..', '.XXXXXX.', 'XX.XX.XX', 'XXXXXXXX', '..X..X..', '.X.XX.X.', 'X.X..X.X'],
  ['..X.....X..', '...X...X...', '..XXXXXXX..', '.XX.XXX.XX.', 'XXXXXXXXXXX', 'X.XXXXXXX.X', 'X.X.....X.X', '...XX.XX...'],
  ['....XXXX....', '.XXXXXXXXXX.', 'XXXXXXXXXXXX', 'XXX..XX..XXX', 'XXXXXXXXXXXX', '...XX..XX...', '..XX.XX.XX..', 'XX........XX'],
  ['....XXXX....', '..XXXXXXXX..', '.XXXXXXXXXX.', 'XX.XX.XX.XX.', 'XXXXXXXXXXXX', '..XXX..XXX..', '...X....X...']
];

// The page sends a move about 30 times a second while keys are held, and
// whenever the direction changes. Each covers the time since the last one.
var SECONDS_PER_MOVE = 1 / 30;
var LONGEST_MOVE = 0.1;

// Tick views arrive 20 times a second. When none has come for this long, the
// session is paused, for example while another runner takes it over, and the
// page sends no moves until they start again.
var PAUSED_AFTER_MS = 500;

// By lower-cased key name, so Shift and Caps Lock don't matter
var KEYS = {
  arrowleft: [-1, 0], arrowright: [1, 0], arrowup: [0, -1], arrowdown: [0, 1],
  a: [-1, 0], d: [1, 0], w: [0, -1], s: [0, 1]
};

// The instructions page creates the participant and their node. The group's
// session starts once every player has a node, so the game page only joins
// it, and can be reloaded while the game is running.
var join_group = function () {
  dallinger.createParticipant().done(function () {
    dallinger.createAgent()
      .done(function () {
        dallinger.goToPage('experiment');
      })
      .fail(function (rejection) {
        // A 403 means every group is full
        if (rejection.status === 403) {
          dallinger.goToPage('questionnaire');
        } else {
          dallinger.error(rejection);
        }
      });
  });
};

var clamp = function (value, low, high) {
  return Math.min(high, Math.max(low, value));
};

var passesNear = function (x1, y1, x2, y2, coin) {
  var sx = x2 - x1;
  var sy = y2 - y1;
  var length = sx * sx + sy * sy;
  var along = length === 0 ? 0 : ((coin.x - x1) * sx + (coin.y - y1) * sy) / length;
  along = clamp(along, 0, 1);
  return Math.hypot(x1 + along * sx - coin.x, y1 + along * sy - coin.y) <= REACH;
};

// Does to the view what the game type's apply does to the state: moves the
// player and collects the coins they pass. It leaves out the cap on movement
// time, which a page moving at the pace of the clock never reaches, and
// touching other players, which the next view shows. predict could also copy
// apply's steals and bounces, for a smoother bump, but that's more than a
// demo needs.
var predict = function (view, message) {
  var player = view.players[view.me];
  var distance = SPEED * message.seconds / Math.hypot(message.dx, message.dy);
  var x = player.x;
  var y = player.y;
  player.x = clamp(x + message.dx * distance, 0, WIDTH);
  player.y = clamp(y + message.dy * distance, 0, HEIGHT);
  view.coins = view.coins.filter(function (coin) {
    if (passesNear(x, y, player.x, player.y, coin)) {
      player.coins += 1;
      return false;
    }
    return true;
  });
};

// Places each player between two tick views, pairing them by participant id.
var interpolate = function (a, b, fraction) {
  var players = {};
  Object.keys(b.players).forEach(function (id) {
    var to = b.players[id];
    var from = a.players[id] || to;
    players[id] = $.extend({}, to, {
      x: from.x + (to.x - from.x) * fraction,
      y: from.y + (to.y - from.y) * fraction
    });
  });
  return $.extend({}, b, {players: players});
};

// now is the session time, for the blink of a player who can't be robbed
var drawPlayer = function (context, player, isMe, now) {
  var rows = SPRITES[player.number - 1];
  var pixel = Math.round(1.1 * SCALE / 12);
  var left = Math.round(player.x * SCALE - rows[0].length * pixel / 2);
  var top = Math.round(player.y * SCALE - rows.length * pixel / 2);
  var color = COLORS[player.number - 1];
  context.save();
  if (isMe) {
    var size = 1.25 * SCALE;
    context.globalAlpha = 0.18;
    context.fillStyle = color;
    context.beginPath();
    context.roundRect(player.x * SCALE - size / 2, player.y * SCALE - size / 2, size, size, size / 4);
    context.fill();
  }
  var blinking = now !== null && now < player.safe_until && Math.floor(now * 8) % 2 === 0;
  context.globalAlpha = blinking ? 0.3 : 1;
  context.fillStyle = color;
  rows.forEach(function (row, i) {
    for (var j = 0; j < row.length; j += 1) {
      if (row[j] === 'X') { context.fillRect(left + j * pixel, top + i * pixel, pixel, pixel); }
    }
  });
  context.restore();
};

// Draws the coins and the player from mine, and the other players from
// others.
var drawArena = function (context, mine, others, now) {
  context.clearRect(0, 0, WIDTH * SCALE, HEIGHT * SCALE);
  mine.coins.forEach(function (coin) {
    context.beginPath();
    context.arc(coin.x * SCALE, coin.y * SCALE, 0.25 * SCALE, 0, 2 * Math.PI);
    context.fillStyle = '#f2b705';
    context.fill();
  });
  Object.keys(others.players).forEach(function (id) {
    if (id !== mine.me) { drawPlayer(context, others.players[id], false, now); }
  });
  drawPlayer(context, mine.players[mine.me], true, now);
};

var shownScores = null;

var showScores = function (view) {
  var scores = Object.keys(view.players).map(function (id) {
    var player = view.players[id];
    return [player.number, (id === view.me ? 'You' : 'Player ' + player.number) + ': ' + player.coins];
  });
  // Called every frame, so the list is only rebuilt when a score changes
  var key = JSON.stringify(scores);
  if (key === shownScores) { return; }
  shownScores = key;
  $('#scores').empty();
  scores.forEach(function (score) {
    $('#scores').append($('<li class="list-inline-item">')
      .css({'background-color': COLORS[score[0] - 1], color: '#fff', padding: '2px 8px', 'border-radius': '4px'})
      .text(score[1]));
  });
};

var describe_result = function (reason, view) {
  // A page reloaded after the game ended, before its result was saved, gets
  // no view
  if (view === null) {
    return 'This game is over.';
  }
  var me = view.players[view.me];
  var mine = me.coins;
  var text = 'You finished with ' + mine + (mine === 1 ? ' coin' : ' coins') +
    ', earning $' + (view.bonus_per_coin * mine).toFixed(2) + '.';
  if (view.stealing) {
    text += ' You stole ' + me.stole + ' and lost ' + me.coins_lost + '.';
  }
  var times = function (n) { return n + (n === 1 ? ' time' : ' times'); };
  if (view.bouncing) {
    text += ' You were bounced ' + times(me.bounced) + ' and bounced others ' +
      times(me.bounced_others) + '.';
  }
  if (reason !== 'max_duration') {
    text += ' The game was stopped early.';
  }
  return text;
};

var play_coins = function () {
  // predict and interpolate are optional. Without them, the page would draw
  // every player from the latest view onView gets, so the player's own moves
  // would show a round trip late and everyone would move in steps of a tick.
  dallinger.joinRealtimeSession('coins', {
    predict: predict,
    interpolate: interpolate
  }).done(function (socket) {
    var context = document.getElementById('arena').getContext('2d');
    var latest = null;
    var lastViewAt = null;
    var ended = false;
    var held = {};
    var direction = [0, 0];
    var heldFor = 0;
    var lastFrame = null;

    $('#waiting').hide();
    $('#game').show();

    socket.onView(function (view) {
      latest = view;
      lastViewAt = performance.now();
      $('#stealing').toggle(view.stealing);
      $('#bouncing').toggle(view.bouncing);
    });

    $(document).on('keydown', function (event) {
      // Leave shortcuts such as Cmd+S alone. Their keyup may never arrive.
      if (event.metaKey || event.ctrlKey || event.altKey) { return; }
      var key = event.key.toLowerCase();
      if (KEYS[key]) {
        held[key] = true;
        event.preventDefault();
      }
    }).on('keyup', function (event) {
      delete held[event.key.toLowerCase()];
    });
    $(window).on('blur', function () { held = {}; });

    var heldDirection = function () {
      var dx = 0;
      var dy = 0;
      Object.keys(held).forEach(function (key) {
        dx += KEYS[key][0];
        dy += KEYS[key][1];
      });
      return [clamp(dx, -1, 1), clamp(dy, -1, 1)];
    };

    var sendMove = function () {
      if (heldFor > 0 && (direction[0] || direction[1])) {
        socket.send('coins', {dx: direction[0], dy: direction[1], seconds: heldFor});
      }
      heldFor = 0;
    };

    var frame = function (now) {
      var elapsed = lastFrame === null ? 0 : (now - lastFrame) / 1000;
      lastFrame = now;
      var paused = lastViewAt === null || now - lastViewAt > PAUSED_AFTER_MS;
      $('#paused').toggle(!ended && lastViewAt !== null && paused);

      var next = heldDirection();
      if (next[0] !== direction[0] || next[1] !== direction[1]) {
        sendMove();
        direction = next;
      }
      if (ended || paused) {
        heldFor = 0;
      } else if (direction[0] || direction[1]) {
        heldFor = Math.min(LONGEST_MOVE, heldFor + elapsed);
        if (heldFor >= SECONDS_PER_MOVE) { sendMove(); }
      }

      var mine = socket.predictedView();
      var others = socket.interpolatedView() || mine;
      if (mine !== null) {
        // Moves go out about 30 times a second, so the player's piece also
        // shows the time the keys have been held since the last one, and
        // moves every frame
        if (heldFor > 0 && (direction[0] || direction[1])) {
          mine = JSON.parse(JSON.stringify(mine));
          predict(mine, {dx: direction[0], dy: direction[1], seconds: heldFor});
        }
        drawArena(context, mine, others, socket.sessionTime());
        showScores(mine);
      }
      var time = socket.sessionTime();
      if (time !== null && latest !== null) {
        $('#timer').text(Math.ceil(Math.max(0, latest.end - time)));
      }
      if (!ended) { requestAnimationFrame(frame); }
    };
    requestAnimationFrame(frame);

    socket.onEnded(function (reason, view) {
      ended = true;
      $('#paused').hide();
      $('#timer').text(0);
      if (view !== null) {
        drawArena(context, view, view, null);
        showScores(view);
      }
      $('#result').text(describe_result(reason, view));
    });

    // Move on once the outcome is saved, so the bonus can be paid from it. The
    // wait fails only if the connection is refused or closed, and then the
    // player can still move on.
    socket.resultSaved().always(function () {
      $('#continue').show();
    });
    $('#continue').on('click', function () {
      dallinger.goToPage('questionnaire');
    });
  }).fail(function (code, reason) {
    $('#waiting').text('Couldn\'t join the game: ' + reason);
  });
};
