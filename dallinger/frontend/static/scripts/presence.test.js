/*globals expect, describe, jest, test, beforeEach, afterEach */

const SECOND = 1000;
const MINUTE = 60 * SECOND;

describe("dallingerPresence", function () {
  let presence;
  let send;
  let clock;
  let pinger;

  function advance(ms) {
    for (let elapsed = 0; elapsed < ms; elapsed += SECOND) {
      clock += SECOND;
      jest.advanceTimersByTime(SECOND);
    }
  }

  function start() {
    pinger = presence.start({
      intervalMs: 20 * SECOND,
      activeWindowMs: MINUTE,
      send: send,
      now: () => clock,
    });
  }

  function addMedia(attributes) {
    const audio = document.createElement("audio");
    Object.defineProperty(audio, "paused", { value: false });
    Object.assign(audio, attributes);
    document.body.appendChild(audio);
  }

  beforeEach(function () {
    jest.useFakeTimers();
    jest.resetModules();
    presence = require("./presence");
    send = jest.fn();
    clock = 0;
  });

  afterEach(function () {
    pinger.stop();
    document.body.innerHTML = "";
    jest.useRealTimers();
  });

  test("pings for one idle window after loading, then stops when left alone", function () {
    start();
    advance(40 * SECOND);
    expect(send).toHaveBeenCalledTimes(2);
    advance(10 * MINUTE);
    expect(send).toHaveBeenCalledTimes(2);
  });

  test("pings at once when someone returns after a quiet spell", function () {
    start();
    advance(5 * MINUTE);
    send.mockClear();
    document.dispatchEvent(new Event("keydown"));
    expect(send).toHaveBeenCalledTimes(1);
    document.dispatchEvent(new Event("keydown"));
    expect(send).toHaveBeenCalledTimes(1);

    advance(5 * MINUTE);
    send.mockClear();
    document.dispatchEvent(new Event("visibilitychange"));
    expect(send).toHaveBeenCalledTimes(1);
  });

  test("keeps pinging while waiting, including when marked before start", function () {
    presence.setWaiting(true);
    start();
    advance(5 * MINUTE);
    expect(send).toHaveBeenCalledTimes(15);
  });

  test("audible media keeps pinging, but looping or muted media does not", function () {
    start();
    advance(5 * MINUTE);
    addMedia({ loop: true });
    addMedia({ muted: true });
    send.mockClear();
    advance(MINUTE);
    expect(send).toHaveBeenCalledTimes(0);

    addMedia({});
    advance(MINUTE);
    expect(send).toHaveBeenCalledTimes(3);
  });

  test("starting again replaces the previous pinger", function () {
    start();
    start();
    advance(40 * SECOND);
    expect(send).toHaveBeenCalledTimes(2);
  });
});
