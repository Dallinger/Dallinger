/*globals expect, describe, jest, test, beforeEach, afterEach */

// A dallinger.Socket that joins a real-time session, run against the real
// ReconnectingWebSocket. The frames it receives are those
// dallinger/realtime/delivery.py documents.

// dallinger2's _initialize() alerts on load under jsdom.
global.window.alert = () => {};

let sockets;

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
  return require("./dallinger2").dallinger;
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
      ...fields,
    },
  });
}

function sentMessages(stub) {
  return stub.sent.map((frame) => {
    expect(frame.indexOf("bids:")).toBe(0);
    return JSON.parse(frame.substring("bids:".length));
  });
}

function unacknowledged(socket) {
  return socket._unacknowledged.map((message) => message.number);
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

    expect(live().sent).toEqual(['chat:{"text":"hi"}']);
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
