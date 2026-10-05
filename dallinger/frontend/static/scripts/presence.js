/*
 * Keep a docker-ssh app awake while someone is actually using a page.
 *
 * docker-ssh idle sleep counts only requests that reach the app's front door.
 * This script POSTs /presence while the page is engaged: someone interacted
 * with it within the idle window, audible non-looping audio or video is
 * playing, or the page is marked as waiting (for example for a partner). An
 * abandoned tab therefore stops pinging one idle window after its last
 * interaction.
 */
(function (root) {
  // Only events a person causes: page scripts also fire scroll and focus.
  var ACTIVITY_EVENTS = [
    "pointerdown",
    "pointermove",
    "keydown",
    "touchstart",
    "wheel",
  ];
  var running = null;
  var waiting = false;

  function defaultSend() {
    if (typeof fetch === "function") {
      fetch("/presence", { method: "POST" }).catch(function () {});
    }
  }

  /**
   * Start pinging /presence while the page is engaged.
   *
   * Starting again stops the previous pinger.
   *
   * @param {Object} options
   * @param {number} options.intervalMs - How often to ping while engaged.
   * @param {number} options.activeWindowMs - How long an interaction counts.
   * @returns {{stop: function()}}
   */
  function start(options) {
    if (running) {
      running.stop();
    }
    var doc = options.document || root.document;
    var now = options.now || Date.now;
    var send = options.send || defaultSend;
    var lastActivity = now();
    var lastPing = now();

    function mediaPlaying() {
      // Looping or muted media is background decoration, which would keep
      // an abandoned tab awake forever.
      return Array.prototype.some.call(
        doc.querySelectorAll("audio, video"),
        function (media) {
          return !media.paused && !media.ended && !media.loop && !media.muted;
        },
      );
    }

    function engaged() {
      return (
        waiting || mediaPlaying() || now() - lastActivity < options.activeWindowMs
      );
    }

    function ping() {
      lastPing = now();
      send();
    }

    function onActivity() {
      lastActivity = now();
      // Ping at once after a quiet spell, so a sleeping app starts waking
      // before the participant submits anything.
      if (now() - lastPing >= options.intervalMs) {
        ping();
      }
    }

    function onVisibilityChange() {
      if (doc.visibilityState === "visible") {
        onActivity();
      }
    }

    ACTIVITY_EVENTS.forEach(function (name) {
      doc.addEventListener(name, onActivity, { capture: true, passive: true });
    });
    doc.addEventListener("visibilitychange", onVisibilityChange);
    var timer = root.setInterval(function () {
      if (engaged()) {
        ping();
      }
    }, options.intervalMs);

    var pinger = {
      stop: function () {
        root.clearInterval(timer);
        ACTIVITY_EVENTS.forEach(function (name) {
          doc.removeEventListener(name, onActivity, { capture: true });
        });
        doc.removeEventListener("visibilitychange", onVisibilityChange);
        if (running === pinger) {
          running = null;
        }
      },
    };
    running = pinger;
    return pinger;
  }

  root.dallingerPresence = {
    start: start,
    /** Mark the page as waiting (true) or not (false), before or after start. */
    setWaiting: function (value) {
      waiting = Boolean(value);
    },
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = root.dallingerPresence;
  }
})(typeof window !== "undefined" ? window : this);
