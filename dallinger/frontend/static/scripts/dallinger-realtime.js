/*globals $, dallinger */
/**
 * @file Adds real-time sessions to the sockets of ``dallinger2.js``, which
 * must be loaded first. The base layout loads both, and this one only when
 * the experiment's ``realtime_games`` isn't empty.
 */

(function () {
  if (typeof dallinger === 'undefined' || dallinger._registerSessionJoin === undefined) {
    throw new Error("dallinger-realtime.js must be loaded after dallinger2.js.");
  }
  var dlgr = dallinger;
  // joinSession is a function declaration, so it can be registered here.
  var shared = dlgr._registerSessionJoin(joinSession);
  // The page has already loaded a copy of this script. Its sockets share
  // one message count, so they all keep using the first copy.
  if (shared === null) { return; }
  var checkSendChannel = shared.checkSendChannel;
  var parsePayload = shared.parsePayload;
  var socketUrl = shared.socketUrl;

  // Sessions count a page's messages by its scope, so the page's sockets
  // share one count.
  var lastMessageNumber = 0;

  // The frames dallinger.realtime.delivery sends a page that joined its
  // session.
  var SESSION_FRAMES = ["realtime_view", "realtime_ended", "realtime_saved"];

  var browserTimeAt = function (performanceNow) {
    return (performance.timeOrigin + performanceNow) / 1000;
  };

  // The library reads the clock through this, not the public name, so that
  // a page replacing dallinger.browserTime can't split envelopes from
  // measurements.
  var readBrowserTime = function () {
    return browserTimeAt(performance.now());
  };

  /**
   * The time now on the browser's clock, in seconds since 1970. Use it to
   * note when something happened on the page, and pass that time to a
   * session socket's ``serverTime`` to put it on the server's clock.
   *
   * This clock keeps counting steadily even if someone changes the
   * computer's clock while the page is open. The browser times saved with
   * a session's messages come from it too.
   *
   * A browser event's ``timeStamp`` comes from the same clock, counted in
   * milliseconds from ``performance.timeOrigin``, so an event's browser time
   * is ``(performance.timeOrigin + event.timeStamp) / 1000``. That is closer
   * to the moment a key was pressed or the mouse clicked than calling
   * ``browserTime`` in the event handler.
   *
   * @example
   * document.addEventListener('keydown', function (event) {
   *   var pressedAt = (performance.timeOrigin + event.timeStamp) / 1000;
   *   var pressedAtOnServer = socket.serverTime(pressedAt);
   * });
   *
   * @returns {number} Seconds since 1970
   * @alias dallinger.browserTime
   */
  dlgr.browserTime = function () {
    return readBrowserTime();
  };

  /**
   * Wait for the experiment to start a session of a game type with this
   * participant as a player, then join it, and get the socket to play it
   * on. This is how a game's page usually starts, since the page often
   * opens before its session exists: the experiment starts the session
   * once a group is complete.
   *
   * It waits as ``waitForRealtimeSession`` does, on a connection of its
   * own, so the promise resolves at once if the participant is already
   * playing a session of the game type, and a page that is reloaded during
   * a game finds its session again. A session whose ending has been saved
   * isn't reported. It then opens the socket with ``openExperimentSocket``.
   * Set the socket's callbacks, such as ``onView``, in the ``done``
   * callback, which runs before the socket has received anything.
   *
   * The options are ``afterSession``, as for ``waitForRealtimeSession``,
   * and the options of ``openExperimentSocket`` other than ``session`` and
   * ``gameChannel``, which it sets itself: ``predict``, ``interpolate``,
   * ``interpolationDelay``, ``channel`` and ``scope``. Both connections use
   * the ``scope``, so the experiment's ``accept_websocket_connection`` sees
   * the same one on each. An experiment that names its pages itself can
   * pass its name for the page as the ``scope``, but each load of a page
   * needs a scope of its own: if a reloaded page reuses its scope while the
   * earlier load is still connected, the session can briefly mix up the two
   * loads' messages. A name that stays the same when the page is reloaded
   * can have ``dallinger.pageScope`` added to it. The ``scope`` can't be
   * ``null``, since the game's views would then reach every page the player
   * has open. A page that also uses a chat channel waits with
   * ``waitForRealtimeSession`` and opens its socket with
   * ``openChatSocket``.
   *
   * The promise is rejected, with the close code and reason, if the server
   * refuses the connection that waits for the session, and with the error
   * if the socket can't be opened. A refusal of the socket itself reaches the
   * socket's ``onRefused`` callback. Call the promise's ``cancel`` method
   * to stop waiting, which leaves the promise unresolved. Once the promise
   * has resolved, ``cancel`` does nothing, and the socket's ``close``
   * method closes the socket.
   *
   * @example
   * dallinger.joinRealtimeSession('sealed_bid').done(function (socket) {
   *   socket.onView(function (view) {
   *     $('#bids-made').text(view.bids_made);
   *   });
   *   $('#bid-form').on('submit', function (event) {
   *     event.preventDefault();
   *     socket.send('sealed_bid', {bid: Number($('#bid').val())});
   *   });
   * });
   *
   * @param {string} gameChannel - The game type's ``channel``
   * @param {Object} [options]
   * @param {number} [options.afterSession] - The id of a session the page
   *   already has, so that only a newer one counts
   * @param {string} [options.scope=dallinger.pageScope] - The page's scope,
   *   on both connections
   * @returns {jQuery.Promise} Resolves with the session's
   *   ``dallinger.Socket``. See :ref:`deferreds-label`
   * @alias dallinger.joinRealtimeSession
   */
  dlgr.joinRealtimeSession = function (gameChannel, options) {
    options = options || {};
    ["session", "gameChannel"].forEach(function (name) {
      if (options[name] != null) {
        throw new Error("joinRealtimeSession sets the " + name + " option itself.");
      }
    });
    if (options.channel != null) { checkSendChannel(options.channel); }
    var socketOptions = $.extend({}, options, {gameChannel: gameChannel});
    checkSessionOptions(socketOptions, true);
    var waiting = dlgr.waitForRealtimeSession(gameChannel, {
      afterSession: options.afterSession,
      scope: options.scope
    });
    // then turns an error opening the socket into a rejection, and passes a
    // refused wait's code and reason on unchanged.
    var promise = waiting.then(function (sessionId) {
      return dlgr.openExperimentSocket($.extend({}, socketOptions, {session: sessionId}));
    });
    promise.cancel = waiting.cancel;
    return promise;
  };

  /**
   * Wait for the experiment to start a session of a game type with this
   * participant as a player, and get the session's id. Most pages use
   * ``joinRealtimeSession``, which also opens the socket. This is for a page
   * that needs the id before it joins, or that joins on ``/chat`` with
   * ``openChatSocket``.
   *
   * If the participant is already a player in a running session of the
   * game type, the promise resolves at once, with the newest such session,
   * so a page that is reloaded during a game finds its session again. A
   * session whose ending has been saved isn't reported.
   *
   * When the participant plays several sessions of the game type, one
   * after another, pass the id of the session the page already has as
   * ``afterSession``, so that only a newer one counts. Otherwise a
   * still-running earlier session is the answer.
   *
   * It waits on a connection of its own to the ``/experiment-socket``
   * route, which closes once it has the id. Like any experiment socket, that
   * connection has the ``scope`` option's scope, is checked by the
   * experiment's ``accept_websocket_connection`` method, and its connecting
   * and disconnecting are published on the
   * ``dallinger_control`` channel. The promise is rejected, with the close
   * code and reason, if the server refuses the connection, for example when
   * ``gameChannel`` isn't one of the experiment's game types' channels.
   *
   * Call the promise's ``cancel`` method to stop waiting. It closes the
   * connection and leaves the promise unresolved.
   *
   * @example
   * dallinger.waitForRealtimeSession('sealed_bid').done(function (sessionId) {
   *   var socket = dallinger.openChatSocket({
   *     channel: 'chatroom',
   *     session: sessionId,
   *     gameChannel: 'sealed_bid'
   *   });
   *   socket.onView(function (view) {
   *     $('#bids-made').text(view.bids_made);
   *   });
   * });
   *
   * @param {string} gameChannel - The game type's ``channel``
   * @param {Object} [options]
   * @param {number} [options.afterSession] - The id of a session the page
   *   already has, so that only a newer one counts
   * @param {string} [options.scope=dallinger.pageScope] - Scope of the
   *   connection that waits; ``null`` sends none
   * @returns {jQuery.Promise} Resolves with the session's id. See
   *   :ref:`deferreds-label`
   * @alias dallinger.waitForRealtimeSession
   */
  dlgr.waitForRealtimeSession = function (gameChannel, options) {
    checkSendChannel(gameChannel);
    if (dlgr.identity.participantId == null) {
      throw new Error("Waiting for a session needs a participant id.");
    }
    var after = options == null || options.afterSession == null ? null : options.afterSession;
    if (after !== null && !/^[0-9]+$/.test(String(after))) {
      throw new Error("afterSession is a session id, a whole number, not " + JSON.stringify(after) + ".");
    }
    var deferred = $.Deferred();
    var raw = new ReconnectingWebSocket(socketUrl("/experiment-socket", {
      worker_id: dlgr.identity.workerId,
      participant_id: dlgr.identity.participantId,
      scope: options == null || options.scope === undefined ? dlgr.pageScope : options.scope,
      wait_for_game: gameChannel,
      after_session: after
    }));
    var prefix = dlgr.REALTIME_SESSION_CHANNEL + ':';
    raw.addEventListener("message", function (event) {
      if (event.data.indexOf(prefix) !== 0) { return; }
      var started = parsePayload(event.data.substring(prefix.length));
      if (started == null || started.type !== "realtime_started" ||
          started.game_type !== gameChannel) {
        return;
      }
      raw.close();
      deferred.resolve(started.session_id);
    });
    dlgr.stopReconnectingIfRefused(raw, function (code, reason) {
      deferred.reject(code, reason);
    });
    var promise = deferred.promise();
    promise.cancel = function () {
      // ReconnectingWebSocket's close() leaves an already scheduled
      // reconnect in place, and its timer calls open() on this instance.
      raw.open = function () {};
      raw.close();
    };
    return promise;
  };

  // A run of clock sync sends this many time requests, one after another.
  var CLOCK_REQUESTS = 5;
  // A request with no answer by then is given up, and the next one sent.
  var CLOCK_ANSWER_TIMEOUT_MS = 2000;
  // The time from the end of one run to the start of the next.
  var CLOCK_SYNC_INTERVAL_MS = 30000;

  // Measures the server's clock against the browser's, keeping the answer
  // with the shortest round trip of each run, the one least delayed on the
  // way, and taking the server's clock to have been read halfway through it.
  // measured gets each run's measurement.
  var ClockSync = function (sendRequest, measured) {
    this._sendRequest = sendRequest;
    this._measured = measured;
    this.measurement = null;
    this._run = null;
    this._timer = null;
    this._lastId = 0;
  };

  ClockSync.prototype.start = function () {
    this.stop();
    this._run = {answers: [], left: CLOCK_REQUESTS, request: null};
    this._request();
  };

  ClockSync.prototype.stop = function () {
    clearTimeout(this._timer);
    this._timer = null;
    this._run = null;
  };

  ClockSync.prototype._request = function () {
    var self = this;
    var run = this._run;
    if (run.left === 0) { return this._finish(); }
    run.left -= 1;
    this._lastId += 1;
    run.request = {id: this._lastId, sentAt: performance.now()};
    this._sendRequest({type: "request", id: this._lastId});
    this._timer = setTimeout(function () { self._request(); }, CLOCK_ANSWER_TIMEOUT_MS);
  };

  ClockSync.prototype.receive = function (answer) {
    var receivedAt = performance.now();
    var request = this._run === null ? null : this._run.request;
    if (request === null || answer.id !== request.id) { return; }
    clearTimeout(this._timer);
    this._run.answers.push({
      browser_time: browserTimeAt((request.sentAt + receivedAt) / 2),
      server_time: answer.clock,
      round_trip: (receivedAt - request.sentAt) / 1000
    });
    this._request();
  };

  ClockSync.prototype._finish = function () {
    var self = this;
    var answers = this._run.answers;
    this._run = null;
    this._timer = setTimeout(function () { self.start(); }, CLOCK_SYNC_INTERVAL_MS);
    if (!answers.length) { return; }
    this.measurement = answers.reduce(function (best, answer) {
      return answer.round_trip < best.round_trip ? answer : best;
    });
    this._measured(this.measurement);
  };

  ClockSync.prototype.serverTime = function (browserTime) {
    var measurement = this.measurement;
    if (measurement === null) { return null; }
    return browserTime + measurement.server_time - measurement.browser_time;
  };

  var copyJson = function (value) {
    return JSON.parse(JSON.stringify(value));
  };

  // A session's recent tick views, oldest first, back to the newest one that
  // interpolation can still start from. delay is in tick intervals.
  var TickBuffer = function (delay) {
    this._delay = delay;
    this.views = [];
  };

  TickBuffer.prototype._behind = function (envelope) {
    return envelope.tick_rate ? this._delay / envelope.tick_rate : 0;
  };

  TickBuffer.prototype.add = function (envelope) {
    var views = this.views;
    // After a pause or a handover, the session's time can go back.
    if (views.length && envelope.time < views[views.length - 1].time) {
      views = this.views = [];
    }
    views.push(envelope);
    // The session time is never behind the newest view's, so nothing earlier
    // than this is drawn again.
    var earliest = envelope.time - this._behind(envelope);
    while (views.length > 1 && views[1].time <= earliest) { views.shift(); }
  };

  // The session time went back with a message view, so the older tick views
  // are behind anything that will be drawn.
  TickBuffer.prototype.keepNewest = function () {
    this.views = this.views.slice(-1);
  };

  TickBuffer.prototype.viewAt = function (now, interpolate) {
    var views = this.views;
    if (!views.length) { return null; }
    var newest = views[views.length - 1];
    // Before the socket's first clock measurement.
    if (now === null) { return newest.view; }
    var at = now - this._behind(newest);
    if (at <= views[0].time) { return views[0].view; }
    for (var i = 1; i < views.length; i += 1) {
      if (views[i].time > at) {
        var a = views[i - 1];
        var b = views[i];
        return interpolate(a.view, b.view, (at - a.time) / (b.time - a.time));
      }
    }
    return newest.view;
  };

  // What a socket knows about the session it joined, and the callbacks it
  // was given for it. sendFrame sends a frame on the socket, or holds it
  // until the connection opens, and returns whether it went now.
  var SessionState = function (sessionId, gameChannel, options, sendFrame) {
    var self = this;
    this.sessionId = sessionId;
    this.gameChannel = gameChannel;
    this._predict = options.predict;
    this._interpolate = options.interpolate;
    this._sendFrame = sendFrame;
    this._callbacks = {view: [], rejected: [], ended: [], saved: [], clock: []};
    // Counts the socket's connections, so each message knows which one it
    // went out on.
    this._connection = 0;
    // Messages sent on the game channel that no view has acknowledged, each
    // with the connection it went out on, or null while it is held.
    this.unacknowledged = [];
    this.view = null;
    this.ended = false;
    this.finalView = null;
    this._saved = $.Deferred();
    this._reportedRejections = {};
    this._prediction = null;
    this._ticks = new TickBuffer(options.interpolationDelay);
    var sendTime = function (frame) {
      sendFrame(dlgr.TIME_CHANNEL + ':' + JSON.stringify(frame));
    };
    this._clock = new ClockSync(sendTime, function (measurement) {
      sendTime($.extend({type: "clock"}, measurement));
      self._notify("clock", [measurement]);
    });
  };

  SessionState.prototype.on = function (kind, callback) {
    this._callbacks[kind].push(callback);
  };

  SessionState.prototype._notify = function (kind, args) {
    this._callbacks[kind].forEach(function (callback) {
      callback.apply(null, args);
    });
  };

  SessionState.prototype.opened = function () {
    var connection = this._connection += 1;
    this.unacknowledged.forEach(function (message) {
      if (message.connection === null) { message.connection = connection; }
    });
    if (!this.ended) { this._clock.start(); }
  };

  // A drop abandons the clock's run, and the next open starts another.
  SessionState.prototype.dropped = function () {
    this._clock.stop();
  };

  // The socket has ended for good, so held messages will never be sent.
  SessionState.prototype.stopped = function (code, reason) {
    this.unacknowledged = this.unacknowledged.filter(function (message) {
      return message.connection !== null;
    });
    this._clock.stop();
    this._saved.reject(code, reason);
  };

  // Sends a message on the game channel, in its envelope, and returns its
  // number.
  SessionState.prototype.send = function (payload) {
    if (typeof payload === 'string') { payload = parsePayload(payload); }
    // The session reads an envelope only if it has a payload key, which
    // JSON.stringify leaves out for undefined.
    if (payload === undefined) { payload = null; }
    var number = lastMessageNumber + 1;
    var body = JSON.stringify({
      envelope: {
        number: number,
        browser_time: readBrowserTime(),
        view_time: this.view === null ? null : this.view.time
      },
      payload: payload
    });
    // A copy, as the game gets it, so a page that changes the object it
    // sent doesn't change what is predicted.
    var copy = copyJson(payload);
    var wentNow = this._sendFrame(this.gameChannel + ':' + body);
    lastMessageNumber = number;
    // No view acknowledges a message sent after the end.
    if (!this.ended) {
      this.unacknowledged.push({
        number: number,
        payload: copy,
        connection: wentNow ? this._connection : null
      });
    }
    return number;
  };

  SessionState.prototype.receive = function (data) {
    if (data == null || data.session_id !== this.sessionId ||
        SESSION_FRAMES.indexOf(data.type) === -1) {
      return;
    }
    if (data.type === "realtime_view") {
      this._receiveView(data.view);
      return;
    }
    if (this._markEnded(data.view)) {
      this._notify("ended", [data.reason, data.view]);
    }
    if (data.type === "realtime_saved" && this._saved.state() === "pending") {
      this._notify("saved", [data]);
      this._saved.resolve(data);
    }
  };

  SessionState.prototype.receiveTime = function (answer) {
    this._clock.receive(answer);
  };

  SessionState.prototype.result = function () {
    return this._saved.promise();
  };

  // Views can arrive out of order: only a newer view is passed on, but one
  // that arrives late still reports its rejections.
  SessionState.prototype._receiveView = function (envelope) {
    var self = this;
    var rejections = envelope.rejected.filter(function (rejection) {
      if (self._reportedRejections[rejection.number]) { return false; }
      self._reportedRejections[rejection.number] = true;
      return true;
    });
    var newest = this.view === null || envelope.number > this.view.number;
    var ending = false;
    if (newest) {
      if (this.view !== null && envelope.time < this.view.time) { this._ticks.keepNewest(); }
      if (envelope.kind === "tick") { this._ticks.add(envelope); }
      this.view = envelope;
      this._acknowledge(envelope.last_processed);
      ending = envelope.ended !== null && this._markEnded(envelope.view);
    }
    rejections.forEach(function (rejection) {
      self._notify("rejected", [rejection.number, rejection.reason]);
    });
    if (!newest) { return; }
    this._notify("view", [envelope.view, envelope]);
    if (ending) { this._notify("ended", [envelope.ended, envelope.view]); }
  };

  // last_processed is the latest of the page's messages the game handled, so
  // it can belong to another socket of the page. This socket's messages reach
  // the game in the order it sent them, so one it names settles every one sent
  // before it. A null last_processed after a reconnect means the session has
  // forgotten the page's numbers, and settles what earlier connections sent.
  SessionState.prototype._acknowledge = function (last) {
    var connection = this._connection;
    var numbers = this.unacknowledged.map(function (message) { return message.number; });
    this.unacknowledged = this.unacknowledged.slice(numbers.indexOf(last) + 1);
    if (last === null) {
      this.unacknowledged = this.unacknowledged.filter(function (message) {
        return message.connection === connection;
      });
    }
  };

  // Returns false if the session was already known to have ended.
  SessionState.prototype._markEnded = function (finalView) {
    if (this.ended) { return false; }
    this.ended = true;
    this.finalView = finalView;
    this._clock.stop();
    return true;
  };

  SessionState.prototype.serverTime = function (browserTime) {
    return this._clock.serverTime(browserTime);
  };

  SessionState.prototype.sessionTime = function () {
    var view = this.view;
    if (view !== null && this.ended) { return view.time; }
    var now = this._clock.serverTime(readBrowserTime());
    if (view === null || now === null) { return null; }
    return view.time + Math.max(0, now - view.clock);
  };

  SessionState.prototype.predictedView = function () {
    if (this._predict === null) {
      throw new Error("This socket was opened without the predict option, so it predicts nothing.");
    }
    if (this.ended) { return this.finalView; }
    if (this.view === null) { return null; }
    // The prediction is reused until the view or the messages change, so
    // pages are told not to change it. Messages are only ever added, or
    // settled when a new view arrives or dropped when the socket stops, so
    // the count tells whether they changed.
    var messages = this.unacknowledged;
    var cached = this._prediction;
    if (cached === null || cached.view !== this.view || cached.count !== messages.length) {
      var predict = this._predict;
      cached = this._prediction = {
        view: this.view,
        count: messages.length,
        predicted: messages.reduce(function (view, message) {
          var next = predict(view, message.payload);
          return next === undefined ? view : next;
        }, copyJson(this.view.view))
      };
    }
    return cached.predicted;
  };

  SessionState.prototype.interpolatedView = function () {
    if (this._interpolate === null) {
      throw new Error("This socket was opened without the interpolate option, so it interpolates nothing.");
    }
    if (this.ended) { return this.finalView; }
    return this._ticks.viewAt(this.sessionTime(), this._interpolate);
  };

  var isFunction = function (value) { return typeof value === 'function'; };

  var isDelay = function (value) {
    return typeof value === 'number' && isFinite(value) && value >= 0;
  };

  // Checks a socket's session options and returns them. hasSession is
  // whether the socket has a session to join.
  var checkSessionOptions = function (options, hasSession) {
    if (hasSession && options.scope === null) {
      throw new Error("A socket that joins a session needs a scope, or the game's views reach every page the player has open.");
    }
    var read = function (name, fallback, check, expected) {
      var value = options[name];
      if (value == null) { return fallback; }
      if (!hasSession) {
        throw new Error("The " + name + " option needs a session.");
      }
      if (!check(value)) {
        throw new Error("The " + name + " option must be " + expected + ".");
      }
      return value;
    };
    var sessionOptions = {
      predict: read("predict", null, isFunction, "a function"),
      interpolate: read("interpolate", null, isFunction, "a function"),
      interpolationDelay: read("interpolationDelay", 2, isDelay, "a number, 0 or more")
    };
    if (options.interpolationDelay != null && sessionOptions.interpolate === null) {
      throw new Error("The interpolationDelay option needs the interpolate option.");
    }
    return sessionOptions;
  };

  // dallinger.Socket's constructor calls this with each new socket, and
  // keeps the session state it returns.
  function joinSession(socket, options) {
    var sessionId = options.session == null ? null : options.session;
    var gameChannel = options.gameChannel == null ? null : options.gameChannel;
    if ((sessionId === null) !== (gameChannel === null)) {
      throw new Error("A socket that joins a session needs both the session and its game type's gameChannel.");
    }
    var sessionOptions = checkSessionOptions(options, sessionId !== null);
    if (sessionId === null) { return null; }
    if (!/^[0-9]+$/.test(String(sessionId))) {
      throw new Error("A session id is a whole number, not " + JSON.stringify(sessionId) + ".");
    }
    checkSendChannel(gameChannel);
    if (socket.participantId == null) {
      throw new Error("A socket that joins a session needs a participant id.");
    }
    return new SessionState(Number(sessionId), gameChannel, sessionOptions, function (frame) {
      return socket._sendFrame(frame);
    });
  }

  dlgr.Socket.prototype._requireSession = function (consequence) {
    if (this._state === null) {
      throw new Error("This socket was opened without a session, so " + consequence + ".");
    }
  };

  dlgr.Socket.prototype._onSession = function (kind, callback) {
    this._requireSession("it receives nothing from one");
    this._state.on(kind, callback);
    return this;
  };

  /**
   * Call ``callback`` with each new view of the game: what the game type's
   * ``view`` method lets this player see. Draw the game from it. The page
   * gets a view when it joins the session, again after a reconnect, and
   * whenever the game changes, until the session ends. The callback only
   * gets views newer than the last one, so it can always draw what it's
   * given.
   *
   * The callback is passed the view, then an object with details about it:
   *
   * - ``view``: the view itself
   * - ``number``: a later view has a higher number
   * - ``time``: the session time the view shows, in seconds (see
   *   ``sessionTime``)
   * - ``kind``: ``"tick"`` if the game type's ``tick`` method made the
   *   change, otherwise ``"message"``
   * - ``last_processed``: the number of this page's latest message that the
   *   game has applied or rejected (see ``send``), or ``null``
   * - ``rejected``: this page's messages the game rejected since its last
   *   view, also passed to ``onRejected``
   * - ``ended``: why the session ended, once it has, otherwise ``null``
   * - ``clock``: the server's clock, in seconds since 1970, when the
   *   session time was ``time``
   * - ``tick_rate``: the game type's ``tick_rate``, how many tick views
   *   arrive a second
   *
   * @param {function} callback - Called with each new view and its details
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onView
   */
  dlgr.Socket.prototype.onView = function (callback) {
    return this._onSession("view", callback);
  };

  /**
   * Call ``callback`` each time the game rejects one of this page's
   * messages, with the number ``send`` returned for the message and the
   * reason the game type's ``apply`` method gave ``Reject``. Use it to tell
   * the player why a move didn't count.
   *
   * Each rejection is reported once. A message rejected just before the
   * connection dropped isn't reported. A page with two sockets in the same
   * session hears each rejection on both.
   *
   * @example
   * socket.onRejected(function (number, reason) {
   *   $('#error').text('That bid didn\'t count: ' + reason);
   * });
   *
   * @param {function} callback - Called with the message's number and the
   *   reason
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onRejected
   */
  dlgr.Socket.prototype.onRejected = function (callback) {
    return this._onSession("rejected", callback);
  };

  /**
   * Call ``callback`` once, as soon as the page learns the session has
   * ended, with the reason it ended and this player's final view. Use it to
   * stop taking moves and show how the game turned out. Don't submit the
   * page yet, since the result may not be saved (see ``resultSaved``).
   *
   * The reason is the one the game type's ``outcome`` method was passed:
   *
   * - ``"finished"``: the game type's ``is_over`` method returned true
   * - ``"max_duration"``: the session ran for the game type's
   *   ``max_duration``
   * - ``"not_joined"``: no player other than a bot joined within the game
   *   type's ``join_timeout``
   * - ``"failed"``: the game's code failed
   * - or the reason the experiment passed to ``end_realtime_session``
   *
   * It also runs for a page that joins after the session has ended, which
   * gets no views. The final view can reach ``onView`` after this callback,
   * so show the result from the view passed here.
   *
   * @param {function} callback - Called with the reason and the final view
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onEnded
   */
  dlgr.Socket.prototype.onEnded = function (callback) {
    return this._onSession("ended", callback);
  };

  /**
   * Call ``callback`` once, when the session's result has been saved, so the
   * page can move on. It does what ``resultSaved`` does, as a callback, and
   * is passed the same object.
   *
   * @param {function} callback - Called with the saved result
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onResultSaved
   */
  dlgr.Socket.prototype.onResultSaved = function (callback) {
    return this._onSession("saved", callback);
  };

  /**
   * Wait for the session's result to be saved. Wait for this before the
   * page is submitted or moves on, so that the experiment can read the
   * result, for example to pay a bonus.
   *
   * The returned promise resolves with an object holding:
   *
   * - ``status``: ``"ended"``, or ``"failed"`` if the game's code failed
   * - ``reason``: why the session ended (see ``onEnded``)
   * - ``view``: this player's final view
   *
   * A failed session's result is saved too, so the page can move on either
   * way. The result is usually saved a moment after the session ends. A page
   * that shouldn't wait indefinitely can use ``onEnded`` to learn that the
   * game is over before then.
   *
   * The promise is rejected if the socket is closed first, or if the server
   * refuses the connection, for example to a page that joins long after the
   * session ended. A refusal passes the close code and reason.
   *
   * @example
   * socket.resultSaved().done(function (result) {
   *   dallinger.goToPage('questionnaire');
   * });
   *
   * @returns {jQuery.Promise} See :ref:`deferreds-label`
   * @alias dallinger.Socket#resultSaved
   */
  dlgr.Socket.prototype.resultSaved = function () {
    this._requireSession("it has no result");
    return this._state.result();
  };

  /**
   * Call ``callback`` each time the socket measures the server's clock.
   * Most pages don't need this, since ``serverTime`` and ``sessionTime``
   * already use the measurements. It is for a page that wants to show or
   * log how closely its clock matches the server's.
   *
   * The socket measures the clock when it connects, then about every 30
   * seconds until the session ends. Each measurement is saved with the
   * session's records, so an analysis can put the browser times of players'
   * messages on the server's clock. Each one counts as a message toward the
   * game type's ``max_messages_per_second`` limit.
   *
   * The callback is passed an object holding:
   *
   * - ``browser_time``: a moment on the browser's clock (see
   *   ``dallinger.browserTime``), in seconds since 1970
   * - ``server_time``: the server's clock at that same moment, in seconds
   *   since 1970
   * - ``round_trip``: how long the server took to answer, in seconds.
   *   ``server_time`` can be off by up to half of this.
   *
   * @param {function} callback - Called with each measurement
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onClock
   */
  dlgr.Socket.prototype.onClock = function (callback) {
    return this._onSession("clock", callback);
  };

  /**
   * Convert a time on the browser's clock to the server's clock. The two
   * clocks can be seconds apart or more, so convert times before comparing
   * what happened on different players' pages.
   *
   * @example
   * var serverNow = socket.serverTime();
   * var clickedOnServer = socket.serverTime(clickedAt);
   *
   * @param {number} [browserTime] - A time from ``dallinger.browserTime``,
   *   in seconds since 1970. Leave it out to convert the time now.
   * @returns {number|null} The same moment on the server's clock, in seconds
   *   since 1970, or ``null`` until the socket's first measurement, which
   *   arrives shortly after it connects
   * @alias dallinger.Socket#serverTime
   */
  dlgr.Socket.prototype.serverTime = function (browserTime) {
    this._requireSession("it has no server clock");
    return this._state.serverTime(browserTime === undefined ? readBrowserTime() : browserTime);
  };

  /**
   * The session's time now, in seconds: the ``now`` the game type's methods
   * would be passed at this moment. Use it to count down to a deadline the
   * game puts in its view, or to show how long ago something in the view
   * happened.
   *
   * It keeps counting between views. A session's clock stops while the
   * session is paused, for example during a redeploy, so the next view can
   * move the time back a little. Once the session has ended, the time stays
   * at the final view's time.
   *
   * @example
   * var deadline = null;
   * socket.onView(function (view) { deadline = view.deadline; });
   * setInterval(function () {
   *   var now = socket.sessionTime();
   *   if (now !== null && deadline !== null) {
   *     $('#timer').text(Math.ceil(Math.max(0, deadline - now)));
   *   }
   * }, 250);
   *
   * @returns {number|null} The session time in seconds, or ``null`` for a
   *   moment after the socket connects, until it has a view and has measured
   *   the server's clock
   * @alias dallinger.Socket#sessionTime
   */
  dlgr.Socket.prototype.sessionTime = function () {
    this._requireSession("it has no session time");
    return this._state.sessionTime();
  };

  /**
   * The view to draw the player's own piece from, with their moves shown
   * at once instead of a round trip later. Call it each time the page
   * draws. Needs the ``predict`` option.
   *
   * It is the newest view, with the player's moves that the game hasn't
   * handled yet applied by ``predict``, in the order they were sent.
   * ``predict(view, message)`` gets a view and a message as it was passed
   * to ``send``, and returns the view as it would be once the game applied
   * the message. It may change the view it's given and return nothing, but
   * must not change the message.
   *
   * ``predict`` has to do to the view what the game type's ``apply`` method
   * does to the state, or the player's piece jumps when the next view
   * arrives. So have each movement message say how far, or for how long,
   * the player moved, rather than having ``tick`` move players while a key
   * is held, which the page can't predict.
   *
   * A move the game rejects is undone by the next view, which in a game
   * with a ``tick_rate`` above 0 is the next tick's view at the latest. A
   * message dropped for going over the game type's
   * ``max_messages_per_second`` limit stays predicted until the game
   * handles a later message from the page.
   *
   * Draw from the returned view without changing it. Once the session has
   * ended, it is the final view.
   *
   * @example
   * var socket = dallinger.openExperimentSocket({
   *   session: sessionId,
   *   gameChannel: 'moves',
   *   predict: function (view, message) {
   *     view.me.x += message.dx;
   *     view.me.y += message.dy;
   *   }
   * });
   * document.addEventListener('keydown', function (event) {
   *   if (event.key === 'ArrowRight') { socket.send('moves', {dx: 1, dy: 0}); }
   * });
   * function draw() {
   *   var view = socket.predictedView();
   *   if (view !== null) { drawPlayer(view.me); }
   *   requestAnimationFrame(draw);
   * }
   * requestAnimationFrame(draw);
   *
   * @returns {Object|null} The predicted view, or ``null`` before the first
   *   view (unless the session has ended)
   * @alias dallinger.Socket#predictedView
   */
  dlgr.Socket.prototype.predictedView = function () {
    this._requireSession("it predicts nothing");
    return this._state.predictedView();
  };

  /**
   * The view to draw other players from, so they move smoothly instead of
   * jumping from one tick view to the next. Call it each time the page
   * draws. Needs the ``interpolate`` option and a game type whose
   * ``tick_rate`` is above 0. A game that also uses prediction draws the
   * player's own piece from ``predictedView``.
   *
   * It shows the game ``interpolationDelay`` tick intervals (two by
   * default) behind ``sessionTime``. ``interpolate(a, b, fraction)`` gets
   * the tick views either side of that time and how far between them it
   * falls, from 0 to 1, and returns a new view in between, leaving ``a`` and
   * ``b`` unchanged. A longer delay copes better with tick views that
   * arrive late, but shows the game further in the past.
   *
   * Draw from the returned view without changing it. Once the session has
   * ended, it is the final view.
   *
   * @example
   * var socket = dallinger.openExperimentSocket({
   *   session: sessionId,
   *   gameChannel: 'moves',
   *   interpolate: function (a, b, fraction) {
   *     return {
   *       others: a.others.map(function (player, i) {
   *         var next = b.others[i];
   *         return {
   *           x: player.x + (next.x - player.x) * fraction,
   *           y: player.y + (next.y - player.y) * fraction
   *         };
   *       })
   *     };
   *   }
   * });
   * function draw() {
   *   var view = socket.interpolatedView();
   *   if (view !== null) { view.others.forEach(drawPlayer); }
   *   requestAnimationFrame(draw);
   * }
   * requestAnimationFrame(draw);
   *
   * @returns {Object|null} The view to draw, or ``null`` before the first
   *   tick view (unless the session has ended)
   * @alias dallinger.Socket#interpolatedView
   */
  dlgr.Socket.prototype.interpolatedView = function () {
    this._requireSession("it interpolates nothing");
    return this._state.interpolatedView();
  };
}());
