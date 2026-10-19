/*globals expect, describe, jest, test, beforeEach, afterEach */

// A dallinger.Socket that joins a real-time session, run against the real
// ReconnectingWebSocket. The frames it receives are those
// dallinger/realtime/delivery.py documents.

// dallinger2's _initialize() alerts on load under jsdom.
global.window.alert = () => {};

let sockets;
let dallinger;

class StubWebSocket {
  constructor(url) {
    this.url = url;
    this.sent = [];
    sockets.push(this);
  }
  close() {}
  send(frame) {
    this.sent.push(frame);
  }
}
StubWebSocket.CONNECTING = 0;
StubWebSocket.OPEN = 1;
StubWebSocket.CLOSING = 2;
StubWebSocket.CLOSED = 3;

function load() {
  jest.resetModules();
  global.WebSocket = StubWebSocket;
  window.WebSocket = StubWebSocket;
  const ReconnectingWebSocket = require("./reconnecting-websocket");
  global.ReconnectingWebSocket = ReconnectingWebSocket;
  window.ReconnectingWebSocket = ReconnectingWebSocket;
  global.store = require("./store+json2.min");
  window.localStorage.clear();
  global.$ = global.jQuery = require("./jquery-4.0.0.min");
  dallinger = require("./dallinger2").dallinger;
  // The browser global dallinger-realtime.js reads.
  global.dallinger = dallinger;
  require("./dallinger-realtime");
  return dallinger;
}

function joined(options) {
  const dallinger = load();
  dallinger.identity.participantId = 7;
  return dallinger.openExperimentSocket({ session: 4, gameChannel: "bids", ...options });
}

function live() {
  return sockets[sockets.length - 1];
}

// Drop the live connection and let ReconnectingWebSocket open the next one.
function reconnect() {
  live().onclose({ code: 1006, reason: "" });
  jest.advanceTimersByTime(120000);
  live().onopen();
  return live();
}

function deliver(payload, channel = "dallinger_realtime_session") {
  live().onmessage({ data: channel + ":" + JSON.stringify(payload) });
}

function view(number, fields) {
  deliver({
    type: "realtime_view",
    session_id: 4,
    view: {
      view: { shown: number },
      number: number,
      time: number / 10,
      kind: "tick",
      last_processed: null,
      rejected: [],
      ended: null,
      clock: 1000 + number,
      tick_rate: 10,
      ...fields,
    },
  });
}

function framesOn(stub, channel) {
  return stub.sent
    .filter((frame) => frame.indexOf(channel + ":") === 0)
    .map((frame) => JSON.parse(frame.substring(channel.length + 1)));
}

function sentMessages(stub) {
  return framesOn(stub, "bids");
}

function unacknowledged(socket) {
  return socket._state.unacknowledged.map((message) => message.number);
}

// How far the fake server's clock is ahead of the browser's, in seconds.
const OFFSET = 500;

function timeRequests(stub = live()) {
  return framesOn(stub, "dallinger_time").filter((frame) => frame.type === "request");
}

function reports(stub = live()) {
  return framesOn(stub, "dallinger_time").filter((frame) => frame.type === "clock");
}

// Answer the live connection's latest time request after a round trip of
// roundTrip ms, the server reading its clock that fraction of the way
// through, and return the server's clock in the answer.
function answer(roundTrip, at = 0.5) {
  const { id } = timeRequests().pop();
  jest.advanceTimersByTime(roundTrip * at);
  const clock = dallinger.browserTime() + OFFSET;
  jest.advanceTimersByTime(roundTrip * (1 - at));
  deliver({ type: "time", id, clock }, "dallinger_time");
  return clock;
}

function synced(roundTrips = [40, 40, 40, 40, 40], at = 0.5, options = {}) {
  const socket = joined(options);
  const measurements = [];
  socket.onClock((measurement) => measurements.push(measurement));
  live().onopen();
  roundTrips.forEach((roundTrip) => answer(roundTrip, at));
  return { socket, measurements };
}

// A view the server played `ago` seconds ago on its clock, showing session
// time `time`.
function viewPlayed(number, time, ago, fields) {
  view(number, { time, clock: dallinger.browserTime() + OFFSET - ago, ...fields });
}

beforeEach(() => {
  jest.useFakeTimers();
  sockets = [];
});

afterEach(() => {
  jest.useRealTimers();
});

describe("joining", () => {
  test("names the session in the connection url, on every connection", () => {
    joined();
    live().onopen();

    reconnect();

    expect(sockets).toHaveLength(2);
    sockets.forEach((stub) => {
      expect(new URL(stub.url).searchParams.get("session")).toBe("4");
    });
  });

  test("needs both a session and its game channel", () => {
    const dallinger = load();

    expect(() => dallinger.openChatSocket({ session: 4 })).toThrow(/gameChannel/);
    expect(() => dallinger.openChatSocket({ gameChannel: "bids" })).toThrow(/gameChannel/);
    expect(sockets).toHaveLength(0);
  });

  test("takes a session id given as a string of digits", () => {
    const socket = joined({ session: "4" });
    const views = [];
    socket.onView((shown) => views.push(shown));
    live().onopen();

    view(1);

    expect(views).toEqual([{ shown: 1 }]);
  });

  test.each([["empty", ""], ["fractional", 1.5]])(
    "refuses a session id that is %s",
    (_, session) => {
      expect(() => joined({ session })).toThrow(/whole number/);
      expect(sockets).toHaveLength(0);
    },
  );

  test("refuses a reserved game channel", () => {
    expect(() => joined({ gameChannel: "dallinger_direct" })).toThrow(/reserved/);
  });

  test("needs a participant id", () => {
    const dallinger = load();

    expect(() => dallinger.openExperimentSocket({ session: 4, gameChannel: "bids" })).toThrow(
      /participant id/,
    );
  });
});

describe("loading dallinger-realtime.js", () => {
  test("before dallinger2.js throws, naming the order", () => {
    jest.resetModules();
    delete global.dallinger;

    expect(() => require("./dallinger-realtime")).toThrow(/after dallinger2\.js/);
  });

  test("twice leaves the page's sockets sharing one message count", () => {
    const first = joined();
    live().onopen();
    first.send("bids", "a");

    jest.isolateModules(() => require("./dallinger-realtime"));
    const second = dallinger.openChatSocket({ session: 4, gameChannel: "bids" });
    live().onopen();

    expect(second.send("bids", "b")).toBe(2);
  });
});

describe("sending on the game channel", () => {
  test("wraps each message in an envelope numbered from 1", () => {
    const socket = joined();
    live().onopen();

    expect(socket.send("bids", { bid: 5 })).toBe(1);
    expect(socket.send("bids", { bid: 6 })).toBe(2);

    const [first, second] = sentMessages(live());
    expect(first).toEqual({
      envelope: { number: 1, browser_time: expect.any(Number), view_time: null },
      payload: { bid: 5 },
    });
    expect(second.envelope.number).toBe(2);
    expect(second.payload).toEqual({ bid: 6 });
  });

  test("takes the browser time in seconds since 1970", () => {
    const socket = joined();
    live().onopen();

    socket.send("bids", "a");
    jest.advanceTimersByTime(1500);
    socket.send("bids", "b");

    const [first, second] = sentMessages(live()).map((each) => each.envelope.browser_time);
    expect(Math.abs(first - Date.now() / 1000 + 1.5)).toBeLessThan(0.01);
    expect(second - first).toBeCloseTo(1.5);
  });

  test("gives the session time of the newest view", () => {
    const socket = joined();
    live().onopen();
    view(3);
    view(2);

    socket.send("bids", "a");

    expect(sentMessages(live())[0].envelope.view_time).toBe(0.3);
  });

  test("puts a string that is JSON in the envelope parsed, and any other as it is", () => {
    const socket = joined();
    live().onopen();

    socket.send("bids", '{"bid": 5}');
    socket.send("bids", "pass");

    expect(sentMessages(live()).map((each) => each.payload)).toEqual([{ bid: 5 }, "pass"]);
  });

  test("never reuses a number after a reconnect", () => {
    const socket = joined();
    live().onopen();
    socket.send("bids", "a");
    live().onclose({ code: 1006, reason: "" });
    socket.send("bids", "held");
    jest.advanceTimersByTime(120000);
    live().onopen();

    socket.send("bids", "b");

    expect(sentMessages(sockets[0]).map((each) => each.envelope.number)).toEqual([1]);
    expect(sentMessages(live()).map((each) => each.envelope.number)).toEqual([2, 3]);
  });

  test("numbers messages across the page's sockets", () => {
    const first = joined();
    live().onopen();
    first.send("bids", "a");

    const second = require("./dallinger2").dallinger.openChatSocket({
      session: 4,
      gameChannel: "bids",
    });
    live().onopen();

    expect([second.send("bids", "b"), first.send("bids", "c")]).toEqual([2, 3]);
  });

  test("sends a message with no payload as a null payload", () => {
    const socket = joined();
    live().onopen();

    socket.send("bids");

    expect(sentMessages(live())[0]).toEqual({
      envelope: expect.objectContaining({ number: 1 }),
      payload: null,
    });
  });

  test("uses no number for a message that can't be encoded", () => {
    const socket = joined();
    live().onopen();
    const circular = {};
    circular.self = circular;

    expect(() => socket.send("bids", circular)).toThrow();
    expect(socket.send("bids", "a")).toBe(1);

    expect(unacknowledged(socket)).toEqual([1]);
  });

  test("sends a message on any other channel without an envelope", () => {
    const socket = joined();
    live().onopen();

    expect(socket.send("chat", { text: "hi" })).toBeUndefined();

    expect(live().sent.filter((frame) => !frame.startsWith("dallinger_time:"))).toEqual([
      'chat:{"text":"hi"}',
    ]);
  });
});

describe("views", () => {
  function watched(options) {
    const socket = joined(options);
    const views = [];
    const directs = [];
    socket.onView((shown, envelope) => views.push([shown, envelope.number]));
    socket.onDirect((data) => directs.push(data));
    live().onopen();
    return { socket, views, directs };
  }

  test("passes each view and its envelope to onView, and not to onDirect", () => {
    const { views, directs } = watched();

    view(1);
    view(2);

    expect(views).toEqual([
      [{ shown: 1 }, 1],
      [{ shown: 2 }, 2],
    ]);
    expect(directs).toEqual([]);
  });

  test("drops a view older than one already passed on", () => {
    const { views } = watched();

    view(5);
    view(4);
    view(5);
    view(6);

    expect(views.map((each) => each[1])).toEqual([5, 6]);
  });

  test("drops frames for another session, and passes directed messages to onDirect", () => {
    const { views, directs } = watched();
    const viewOf = (sessionId) => ({
      type: "realtime_view",
      session_id: sessionId,
      view: { number: 1, rejected: [], last_processed: null, ended: null },
    });

    deliver(viewOf(5));
    deliver(viewOf(4), "dallinger_direct");
    deliver(null, "dallinger_direct");

    expect(views).toEqual([]);
    expect(directs).toEqual([viewOf(4), null]);
  });

  test("refuse callbacks on a socket without a session", () => {
    const socket = load().openExperimentSocket();

    expect(() => socket.onView(() => {})).toThrow();
    expect(() => socket.onRejected(() => {})).toThrow();
    expect(() => socket.onEnded(() => {})).toThrow();
    expect(() => socket.onResultSaved(() => {})).toThrow();
    expect(() => socket.resultSaved()).toThrow(/without a session/);
    expect(() => socket.onClock(() => {})).toThrow();
    expect(() => socket.serverTime()).toThrow(/without a session/);
    expect(() => socket.sessionTime()).toThrow(/without a session/);
  });

  test("a socket without a session passes no session frame to onDirect", () => {
    const dallinger = load();
    dallinger.identity.participantId = 7;
    const socket = dallinger.openExperimentSocket();
    const directs = [];
    socket.onDirect((data) => directs.push(data));
    live().onopen();

    deliver({ type: "realtime_saved", session_id: 4, status: "ended" });

    expect(directs).toEqual([]);
  });
});

describe("acknowledgments", () => {
  test("a view acknowledges the message it names and every one sent before it", () => {
    const socket = joined();
    live().onopen();
    ["a", "b", "c"].forEach((each) => socket.send("bids", each));

    view(1, { last_processed: 2 });

    expect(unacknowledged(socket)).toEqual([3]);
  });

  test("a view naming a message this socket didn't send acknowledges none of its own", () => {
    const socket = joined();
    live().onopen();
    ["a", "b"].forEach((each) => socket.send("bids", each));

    view(1, { last_processed: 7 });

    expect(unacknowledged(socket)).toEqual([1, 2]);
  });

  test("an older view acknowledges nothing", () => {
    const socket = joined();
    live().onopen();
    ["a", "b"].forEach((each) => socket.send("bids", each));
    view(2, { last_processed: 1 });

    view(1, { last_processed: 2 });

    expect(unacknowledged(socket)).toEqual([2]);
  });

  test.each([
    ["closed", (socket) => socket.close()],
    [
      "refused",
      () => {
        jest.advanceTimersByTime(120000);
        live().onclose({ code: 1008, reason: "not a player in this session" });
      },
    ],
  ])("a socket that is %s keeps only the messages it sent", (_, end) => {
    const socket = joined();
    socket.onRefused(() => {});
    live().onopen();
    socket.send("bids", "sent");
    live().onclose({ code: 1006, reason: "" });
    socket.send("bids", "held");

    end(socket);

    expect(unacknowledged(socket)).toEqual([1]);
  });

  test("after a reconnect, a view the session sends without a last_processed settles every message sent before the drop", () => {
    const socket = joined();
    live().onopen();
    ["a", "b"].forEach((each) => socket.send("bids", each));
    view(1);
    expect(unacknowledged(socket)).toEqual([1, 2]);
    live().onclose({ code: 1006, reason: "" });
    socket.send("bids", "held");

    jest.advanceTimersByTime(120000);
    live().onopen();
    socket.send("bids", "after");
    view(2);

    expect(unacknowledged(socket)).toEqual([3, 4]);
  });

  test("after a reconnect, a view naming an earlier message keeps the ones sent after it", () => {
    const socket = joined();
    live().onopen();
    ["a", "b"].forEach((each) => socket.send("bids", each));

    reconnect();
    view(1, { last_processed: 1 });

    expect(unacknowledged(socket)).toEqual([2]);
  });
});

describe("rejections", () => {
  test("are reported once each, with the number and reason, even from a late view", () => {
    const socket = joined();
    const rejected = [];
    socket.onRejected((number, reason) => rejected.push([number, reason]));
    live().onopen();

    view(2, { rejected: [{ number: 3, reason: "too low" }] });
    view(1, { rejected: [{ number: 1, reason: { code: "late" } }] });
    view(2, { rejected: [{ number: 3, reason: "too low" }] });

    expect(rejected).toEqual([
      [3, "too low"],
      [1, { code: "late" }],
    ]);
  });

  test("leave the view's state in place if a callback throws", () => {
    const errors = [];
    const caught = (event) => {
      errors.push(event.error.message);
      event.preventDefault();
    };
    window.addEventListener("error", caught);
    const socket = joined();
    socket.onRejected(() => {
      throw new Error("page bug");
    });
    live().onopen();
    socket.send("bids", "a");

    view(2, { last_processed: 1, rejected: [{ number: 1, reason: "no" }] });
    socket.send("bids", "b");
    window.removeEventListener("error", caught);

    expect(errors).toEqual(["page bug"]);
    expect(unacknowledged(socket)).toEqual([2]);
    expect(sentMessages(live())[1].envelope.view_time).toBe(0.2);
  });
});

describe("the ending", () => {
  function watched() {
    const socket = joined();
    const events = [];
    socket.onEnded((reason, shown) => events.push(["ended", reason, shown]));
    socket.onResultSaved((result) => events.push(["saved", result.status]));
    live().onopen();
    return { socket, events };
  }

  const saved = {
    type: "realtime_saved",
    session_id: 4,
    status: "failed",
    reason: "failed",
    view: { shown: "final" },
  };

  test("is reported once, from the first view that says the session ended", () => {
    const { events } = watched();

    view(1);
    view(2, { ended: "finished" });
    view(3, { ended: "finished" });

    expect(events).toEqual([["ended", "finished", { shown: 2 }]]);
  });

  test("is reported from the ending a page gets when it joins an ended session", () => {
    const { socket, events } = watched();

    deliver({ type: "realtime_ended", session_id: 4, reason: "finished", view: { shown: "final" } });

    expect(events).toEqual([["ended", "finished", { shown: "final" }]]);
    expect(socket.resultSaved().state()).toBe("pending");
  });

  test("once saved, resolves the result promise and calls onResultSaved, once", () => {
    const { socket, events } = watched();
    const result = socket.resultSaved();
    expect(result.state()).toBe("pending");
    expect(result.resolve).toBeUndefined();

    deliver(saved);
    deliver(saved);

    let resolved = null;
    result.done((value) => {
      resolved = value;
    });
    expect(resolved).toEqual(saved);
    expect(events).toEqual([
      ["ended", "failed", { shown: "final" }],
      ["saved", "failed"],
    ]);
  });

  test.each([
    ["refused", () => live().onclose({ code: 1008, reason: "not a player in this session" }), [1008, "not a player in this session"]],
    ["closed", (socket) => socket.close(), [undefined, undefined]],
  ])("rejects the result promise if the socket is %s first", (_, end, expected) => {
    const { socket } = watched();
    socket.onRefused(() => {});
    let failure = null;
    socket.resultSaved().fail((code, reason) => {
      failure = [code, reason];
    });

    end(socket);

    expect(failure).toEqual(expected);
  });

  test("ignores another session's saved result", () => {
    const { socket, events } = watched();

    deliver({ ...saved, session_id: 5 });

    expect(socket.resultSaved().state()).toBe("pending");
    expect(events).toEqual([]);
  });

  test("ignores a session frame of a type it doesn't know", () => {
    const { socket, events } = watched();

    deliver({ ...saved, type: "realtime_paused" });

    expect(socket.resultSaved().state()).toBe("pending");
    expect(events).toEqual([]);
  });
});

describe("clock sync", () => {
  test("sends five requests on connect, each once the last is answered", () => {
    joined();
    live().onopen();

    const counts = [timeRequests().length];
    for (let i = 0; i < 5; i += 1) {
      answer(20);
      counts.push(timeRequests().length);
    }

    expect(counts).toEqual([1, 2, 3, 4, 5, 5]);
    expect(new Set(timeRequests().map((request) => request.id)).size).toBe(5);
  });

  test("keeps the answer with the shortest round trip, and reports it once", () => {
    const socket = joined();
    const measurements = [];
    socket.onClock((measurement) => measurements.push(measurement));
    live().onopen();
    // The server reads its clock early on the slower requests, so only the
    // fastest one gives the clock exactly.
    answer(80, 0.1);
    answer(60, 0.1);
    const clock = answer(20, 0.5);
    answer(70, 0.1);
    answer(90, 0.1);

    expect(measurements).toHaveLength(1);
    const [{ browser_time, server_time, round_trip }] = measurements;
    expect([server_time, round_trip]).toEqual([clock, expect.closeTo(0.02, 6)]);
    expect(browser_time).toBeCloseTo(clock - OFFSET, 6);
    expect(reports()).toEqual([{ type: "clock", ...measurements[0] }]);
    expect(socket.serverTime() - dallinger.browserTime()).toBeCloseTo(OFFSET, 6);
  });

  test("converts a browser time to the server's", () => {
    const { socket } = synced();
    const then = dallinger.browserTime() - 30;

    expect(socket.serverTime(then)).toBeCloseTo(then + OFFSET, 6);
  });

  test("measures again every 30 s, the newest measurement replacing the last", () => {
    const { socket, measurements } = synced([10, 10, 10, 10, 10]);

    jest.advanceTimersByTime(29999);
    expect(timeRequests()).toHaveLength(5);
    jest.advanceTimersByTime(1);
    expect(timeRequests()).toHaveLength(6);
    // The server reads its clock 30 ms into a 100 ms round trip, so this
    // measurement puts the server 20 ms further behind than the last.
    [100, 100, 100, 100, 100].forEach((roundTrip) => answer(roundTrip, 0.3));

    expect(measurements.map((each) => each.round_trip)).toEqual([
      expect.closeTo(0.01, 6),
      expect.closeTo(0.1, 6),
    ]);
    expect(reports()).toHaveLength(2);
    expect(socket.serverTime() - dallinger.browserTime()).toBeCloseTo(OFFSET - 0.02, 6);
  });

  test("keeps measuring every 30 s when an onClock callback throws", () => {
    const errors = [];
    const caught = (event) => {
      errors.push(event.error.message);
      event.preventDefault();
    };
    window.addEventListener("error", caught);
    const socket = joined();
    socket.onClock(() => {
      throw new Error("page bug");
    });
    live().onopen();
    [10, 10, 10, 10, 10].forEach((roundTrip) => answer(roundTrip));
    window.removeEventListener("error", caught);

    jest.advanceTimersByTime(30000);

    expect(errors).toEqual(["page bug"]);
    expect(timeRequests()).toHaveLength(6);
  });

  test("abandons a run when the connection drops, keeping the last measurement", () => {
    const { socket, measurements } = synced();
    jest.advanceTimersByTime(30000);
    answer(30);
    answer(30);
    const before = live();
    const outstanding = timeRequests().pop();

    before.onclose({ code: 1006, reason: "" });
    jest.advanceTimersByTime(120000);
    live().onopen();
    deliver({ type: "time", id: outstanding.id, clock: 0 }, "dallinger_time");

    expect(timeRequests(before)).toHaveLength(8);
    expect(measurements).toHaveLength(1);
    expect(reports(before)).toHaveLength(1);
    expect(socket.serverTime() - dallinger.browserTime()).toBeCloseTo(OFFSET, 6);
    expect(timeRequests()).toHaveLength(1);
    expect(reports()).toEqual([]);
  });

  test("gives up on each request after 2 s, ignoring a late answer", () => {
    const { socket, measurements } = synced([]);
    const [first] = timeRequests();

    jest.advanceTimersByTime(2000);
    deliver({ type: "time", id: first.id, clock: 0 }, "dallinger_time");
    expect(timeRequests()).toHaveLength(2);
    jest.advanceTimersByTime(8000);
    expect(timeRequests()).toHaveLength(5);
    jest.advanceTimersByTime(29999);
    expect(timeRequests()).toHaveLength(5);
    jest.advanceTimersByTime(1);

    expect(timeRequests()).toHaveLength(6);
    expect(measurements).toEqual([]);
    expect(reports()).toEqual([]);
    expect(socket.serverTime()).toBeNull();
  });

  test("stops at the view that ends the session, even if an onView callback throws", () => {
    const errors = [];
    const caught = (event) => {
      errors.push(event.error.message);
      event.preventDefault();
    };
    window.addEventListener("error", caught);
    const { socket } = synced();
    const seen = [];
    socket.onView(() => {
      seen.push(socket.sessionTime());
      throw new Error("page bug");
    });

    view(1, { ended: "finished" });
    window.removeEventListener("error", caught);
    jest.advanceTimersByTime(60000);

    expect(errors).toEqual(["page bug"]);
    expect(seen).toEqual([0.1]);
    expect(timeRequests()).toHaveLength(5);
    expect(socket.sessionTime()).toBe(0.1);
  });

  test("keeps its own clock when a page replaces dallinger.browserTime", () => {
    const { socket } = synced();
    const now = dallinger.browserTime();

    dallinger.browserTime = () => 0;
    socket.send("bids", "a");

    expect(sentMessages(live())[0].envelope.browser_time).toBeCloseTo(now, 6);
    expect(socket.serverTime()).toBeCloseTo(now + OFFSET, 6);
  });

  test("stops when the session ends, and doesn't start again on a reconnect", () => {
    const { socket } = synced([20]);
    view(1, { ended: "finished" });
    answer(20);

    jest.advanceTimersByTime(60000);
    reconnect();
    jest.advanceTimersByTime(60000);

    expect(timeRequests(sockets[0])).toHaveLength(2);
    expect(timeRequests()).toEqual([]);
    expect(reports(sockets[0])).toEqual([]);
    expect(socket.serverTime()).toBeNull();
  });

  test("stops when the socket is closed", () => {
    const socket = joined();
    live().onopen();

    socket.close();
    jest.advanceTimersByTime(60000);

    expect(timeRequests()).toHaveLength(1);
  });

  describe("the session time", () => {
    test("is unknown without both a view and a measurement", () => {
      const socket = joined();
      live().onopen();
      answer(20);
      viewPlayed(1, 12, 0);
      expect(socket.serverTime()).toBeNull();
      expect(socket.sessionTime()).toBeNull();

      const { socket: unseen } = synced();
      expect(unseen.sessionTime()).toBeNull();
    });

    test("goes on from the newest view's time, within half a round trip", () => {
      // The server reads its clock 35 ms into each 50 ms round trip, 10 ms
      // after the midpoint the page assumes.
      const { socket } = synced([50, 50, 50, 50, 50], 0.7);
      viewPlayed(2, 12, 0.08);
      viewPlayed(1, 99, 0);

      expect(Math.abs(socket.sessionTime() - 12.08)).toBeLessThanOrEqual(0.025);
      jest.advanceTimersByTime(1500);
      expect(Math.abs(socket.sessionTime() - 13.58)).toBeLessThanOrEqual(0.025);
    });

    test("follows the newest view back after the session's clock stopped", () => {
      const { socket } = synced();
      viewPlayed(1, 12, 0);
      jest.advanceTimersByTime(3000);
      expect(socket.sessionTime()).toBeCloseTo(15, 6);

      // The session's clock stopped for 2 s, so the view after the pause
      // shows 1 s on from the last one.
      viewPlayed(2, 13, 0);

      expect(socket.sessionTime()).toBeCloseTo(13, 6);
    });

    test("is never behind the newest view's time", () => {
      const { socket } = synced();

      viewPlayed(1, 12, -0.5);

      expect(socket.sessionTime()).toBe(12);
    });

    test("stays at the newest view's time once the session has ended", () => {
      const { socket } = synced();
      viewPlayed(1, 12, 0);
      viewPlayed(2, 12.5, 0);
      deliver({ type: "realtime_ended", session_id: 4, reason: "finished", view: {} });

      jest.advanceTimersByTime(5000);

      expect(socket.sessionTime()).toBe(12.5);
    });

    test("is the ending view's time when the session ends before a measurement", () => {
      const socket = joined();
      live().onopen();

      viewPlayed(1, 12, 0);
      view(2, { time: 12.5, ended: "finished" });

      expect(socket.serverTime()).toBeNull();
      expect(socket.sessionTime()).toBe(12.5);
    });
  });
});

describe("prediction and interpolation options", () => {
  test.each([
    ["predict", "x", /predict option must be a function/],
    ["interpolate", {}, /interpolate option must be a function/],
    ["interpolationDelay", -1, /must be a number, 0 or more/],
    ["interpolationDelay", "2", /must be a number, 0 or more/],
    ["interpolationDelay", Infinity, /must be a number, 0 or more/],
    ["interpolationDelay", 1, /needs the interpolate option/],
  ])("refuse a %s of %p", (name, value, error) => {
    expect(() => joined({ [name]: value })).toThrow(error);
  });

  test("need a session", () => {
    const dallinger = load();
    dallinger.identity.participantId = 7;

    expect(() => dallinger.openExperimentSocket({ predict: () => {} })).toThrow(/needs a session/);
    expect(sockets).toHaveLength(0);
  });
});

describe("prediction", () => {
  const record = (view, message) => {
    view.log.push(message);
  };

  test("applies predict to a copy of the newest view, for each unacknowledged message in order", () => {
    const socket = joined({ predict: record });
    const views = [];
    socket.onView((shown) => views.push(shown));
    live().onopen();
    ["a", "b", "c"].forEach((each) => socket.send("bids", each));

    view(1, { last_processed: 1, view: { log: ["a"] } });

    expect(socket.predictedView()).toEqual({ log: ["a", "b", "c"] });
    expect(views).toEqual([{ log: ["a"] }]);
  });

  test("takes the view a predict returns", () => {
    const socket = joined({ predict: (view, message) => ({ n: view.n + message.step }) });
    live().onopen();
    socket.send("bids", { step: 1 });
    socket.send("bids", '{"step": 2}');

    view(1, { view: { n: 10 } });

    expect(socket.predictedView()).toEqual({ n: 13 });
  });

  test("a rejected prediction is undone by the next view", () => {
    const socket = joined({ predict: record });
    live().onopen();
    view(1, { view: { log: [] } });
    socket.send("bids", "into the wall");
    expect(socket.predictedView()).toEqual({ log: ["into the wall"] });

    view(2, { last_processed: 1, rejected: [{ number: 1, reason: "wall" }], view: { log: [] } });

    expect(socket.predictedView()).toEqual({ log: [] });
  });

  test("is worked out again only after a send or a view", () => {
    let calls = 0;
    const socket = joined({
      predict: (view, message) => {
        calls += 1;
        record(view, message);
      },
    });
    live().onopen();
    view(1, { view: { log: [] } });
    socket.send("bids", "a");

    const first = socket.predictedView();
    expect(socket.predictedView()).toBe(first);
    expect(calls).toBe(1);

    socket.send("bids", "b");
    expect(socket.predictedView()).toEqual({ log: ["a", "b"] });
    expect(calls).toBe(3);

    view(2, { view: { log: ["x"] } });
    expect(socket.predictedView()).toEqual({ log: ["x", "a", "b"] });
    expect(calls).toBe(5);
  });

  test("predicts messages held while the connection is down, until the socket is closed", () => {
    const socket = joined({ predict: record });
    live().onopen();
    socket.send("bids", "sent");
    view(1, { view: { log: [] } });
    live().onclose({ code: 1006, reason: "" });

    socket.send("bids", "held");
    expect(socket.predictedView()).toEqual({ log: ["sent", "held"] });

    socket.close();
    expect(socket.predictedView()).toEqual({ log: ["sent"] });
  });

  test("is the final view once the session has ended, whatever is sent after", () => {
    const socket = joined({ predict: record });
    live().onopen();
    view(1, { view: { log: [] } });

    deliver({ type: "realtime_ended", session_id: 4, reason: "finished", view: { log: ["final"] } });
    socket.send("bids", "late");

    expect(socket.predictedView()).toEqual({ log: ["final"] });
    expect(unacknowledged(socket)).toEqual([]);
  });

  test("predicts each message as it was sent, even if the page changes the object later", () => {
    const socket = joined({ predict: (view, message) => ({ n: view.n + message.step }) });
    live().onopen();
    view(1, { view: { n: 0 } });
    const move = { step: 1 };

    socket.send("bids", move);
    move.step = 10;
    socket.send("bids", move);

    expect(socket.predictedView()).toEqual({ n: 11 });
  });

  test("is null until the first view", () => {
    const socket = joined({ predict: record });
    live().onopen();
    socket.send("bids", "a");

    expect(socket.predictedView()).toBeNull();
  });

  test("needs the predict option", () => {
    expect(() => joined().predictedView()).toThrow(/without the predict option/);
    expect(() => load().openExperimentSocket().predictedView()).toThrow(/without a session/);
  });
});

describe("interpolation", () => {
  const between = (a, b, fraction) => ({ from: a.shown, to: b.shown, fraction });

  function interpolating(options) {
    return synced(undefined, undefined, { interpolate: between, ...options }).socket;
  }

  // Tick views 1 to 4 at session times 1.0 to 1.3, the last played just now.
  function fourTicks(fields) {
    [1, 2, 3, 4].forEach((number) => {
      viewPlayed(number, 0.9 + number / 10, (4 - number) / 10, fields);
    });
  }

  test("draws between the tick views around two tick intervals before the session time, leaving message views out", () => {
    const socket = interpolating();
    viewPlayed(1, 1.0, 0.3);
    viewPlayed(2, 1.1, 0.2);
    viewPlayed(3, 1.15, 0.15, { kind: "message", view: { shown: "message" } });
    viewPlayed(4, 1.2, 0.1);
    viewPlayed(5, 1.3, 0);

    jest.advanceTimersByTime(40);

    expect(socket.interpolatedView()).toEqual({ from: 2, to: 4, fraction: expect.closeTo(0.4, 4) });
  });

  test.each([
    [1, 10, { from: 3, to: 4, fraction: expect.closeTo(0.25, 4) }],
    [2, 0, { shown: 4 }],
  ])("draws %p tick intervals behind at a tick rate of %p", (interpolationDelay, tickRate, expected) => {
    const socket = interpolating({ interpolationDelay });
    fourTicks({ tick_rate: tickRate });

    jest.advanceTimersByTime(25);

    expect(socket.interpolatedView()).toEqual(expected);
  });

  test("starts again from a tick view whose time goes back", () => {
    const socket = interpolating();
    fourTicks();

    viewPlayed(5, 0.9, 0);
    expect(socket.interpolatedView()).toEqual({ shown: 5 });

    jest.advanceTimersByTime(100);
    viewPlayed(6, 1.0, 0);
    jest.advanceTimersByTime(150);

    expect(socket.interpolatedView()).toEqual({ from: 5, to: 6, fraction: expect.closeTo(0.5, 4) });
  });

  test("keeps a tick view at the previous one's time with those before it", () => {
    const socket = interpolating();
    viewPlayed(1, 1.0, 0.2);
    viewPlayed(2, 1.1, 0.1);
    viewPlayed(3, 1.2, 0);
    viewPlayed(4, 1.2, 0);

    jest.advanceTimersByTime(50);

    expect(socket.interpolatedView()).toEqual({ from: 1, to: 2, fraction: expect.closeTo(0.5, 4) });
  });

  test("is the newest tick view when a message view's time goes back", () => {
    const socket = interpolating();
    fourTicks();

    viewPlayed(5, 0.9, 0, { kind: "message" });

    expect(socket.interpolatedView()).toEqual({ shown: 4 });
  });

  test("is the nearest tick view when there isn't one on each side", () => {
    const socket = interpolating();
    viewPlayed(1, 1.0, 0.1);
    viewPlayed(2, 1.1, 0);
    expect(socket.interpolatedView()).toEqual({ shown: 1 });

    jest.advanceTimersByTime(500);

    expect(socket.interpolatedView()).toEqual({ shown: 2 });
  });

  test("is the newest tick view until the server's clock is measured", () => {
    const socket = joined({ interpolate: between });
    live().onopen();

    view(1);
    view(2);
    view(3, { kind: "message" });

    expect(socket.interpolatedView()).toEqual({ shown: 2 });
  });

  test("is null until the first tick view", () => {
    const socket = interpolating();

    viewPlayed(1, 1.0, 0, { kind: "message" });

    expect(socket.interpolatedView()).toBeNull();
  });

  test("is the final view once the session has ended", () => {
    const socket = interpolating();
    fourTicks();

    deliver({ type: "realtime_ended", session_id: 4, reason: "finished", view: { shown: "final" } });

    expect(socket.interpolatedView()).toEqual({ shown: "final" });
  });

  test("keeps only the tick views it can still draw from", () => {
    const socket = interpolating();

    for (let number = 1; number <= 20; number += 1) {
      viewPlayed(number, number, 0, { tick_rate: 1 });
    }

    expect(socket._state._ticks.views.map((each) => each.time)).toEqual([18, 19, 20]);
  });

  test("needs the interpolate option", () => {
    expect(() => joined().interpolatedView()).toThrow(/without the interpolate option/);
    expect(() => load().openExperimentSocket().interpolatedView()).toThrow(/without a session/);
  });
});
