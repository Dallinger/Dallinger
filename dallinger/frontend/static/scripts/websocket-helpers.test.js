/*globals expect, describe, jest, test, beforeEach, afterEach */

// dallinger.openChatSocket, dallinger.openExperimentSocket and the
// dallinger.Socket they return, run against the real ReconnectingWebSocket.

// dallinger2's _initialize() alerts on load under jsdom.
global.window.alert = () => {};

let sockets;

class StubWebSocket {
  constructor(url) {
    this.url = url;
    this.sent = [];
    this.closedWith = null;
    sockets.push(this);
  }
  close(code, reason) {
    this.closedWith = [code, reason];
  }
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
  global.$ = global.jQuery = require("./jquery-3.7.1.min");
  return require("./dallinger2").dallinger;
}

function query(stub) {
  return new URL(stub.url).searchParams;
}

// Drop the live connection and let ReconnectingWebSocket open the next one.
function reconnect() {
  sockets[sockets.length - 1].onclose({ code: 1006, reason: "" });
  jest.advanceTimersByTime(120000);
  return sockets[sockets.length - 1];
}

beforeEach(() => {
  jest.useFakeTimers();
  sockets = [];
});

afterEach(() => {
  jest.useRealTimers();
});

describe("the connection url", () => {
  test("names the route, channel, identity and page scope, encoded", () => {
    const dallinger = load();
    dallinger.identity.workerId = "w 1&x";
    dallinger.identity.participantId = 7;

    dallinger.openChatSocket({ channel: "room 1" });

    const url = new URL(sockets[0].url);
    expect(url.protocol).toBe("ws:");
    expect(url.pathname).toBe("/chat");
    expect(url.searchParams.get("channel")).toBe("room 1");
    expect(url.searchParams.get("worker_id")).toBe("w 1&x");
    expect(url.searchParams.get("participant_id")).toBe("7");
    expect(url.searchParams.get("scope")).toBe(dallinger.pageScope);
  });

  test("uses the experiment socket route", () => {
    const dallinger = load();

    dallinger.openExperimentSocket();

    expect(new URL(sockets[0].url).pathname).toBe("/experiment-socket");
  });

  test("carries a scope the caller names instead of the page scope", () => {
    const dallinger = load();

    dallinger.openChatSocket({ scope: "round-3" });

    expect(query(sockets[0]).get("scope")).toBe("round-3");
  });

  test("leaves out a null scope and anything the identity lacks", () => {
    const dallinger = load();

    dallinger.openChatSocket({ scope: null });

    expect(Array.from(query(sockets[0]).keys())).toEqual([]);
  });
});

describe("sending", () => {
  test("encodes an object as JSON after the channel prefix", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    sockets[0].onopen();

    socket.send("moves", { action: "rock" });

    expect(sockets[0].sent).toEqual(['moves:{"action":"rock"}']);
  });

  test("sends a string payload as it is", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    sockets[0].onopen();

    socket.send("moves", "rock");

    expect(sockets[0].sent).toEqual(["moves:rock"]);
  });

  test("holds messages until the connection opens, then sends them in order", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();

    socket.send("moves", "one");
    socket.send("moves", "two");
    expect(sockets[0].sent).toEqual([]);

    sockets[0].onopen();
    expect(sockets[0].sent).toEqual(["moves:one", "moves:two"]);
  });

  test("holds a message sent while reconnecting for the next connection", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    sockets[0].onopen();
    sockets[0].onclose({ code: 1006, reason: "" });

    socket.send("moves", "rock");
    jest.advanceTimersByTime(120000);
    const next = sockets[sockets.length - 1];
    next.onopen();

    expect(next).not.toBe(sockets[0]);
    expect(next.sent).toEqual(["moves:rock"]);
  });

  test("sends held messages before open callbacks run", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    socket.onOpen(() => socket.send("moves", "from-callback"));

    socket.send("moves", "held");
    sockets[0].onopen();

    expect(sockets[0].sent).toEqual(["moves:held", "moves:from-callback"]);
  });

  test.each([
    ["an empty name", ""],
    ["a name containing a colon", "a:b"],
    ["the control channel", "dallinger_control"],
    ["the direct channel", "dallinger_direct"],
    ["a name that is not a string", ["moves"]],
  ])("refuses %s", (_, channel) => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    sockets[0].onopen();

    expect(() => socket.send(channel, "x")).toThrow();
    expect(sockets[0].sent).toEqual([]);
  });

  test("discards a message sent after close", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    sockets[0].onopen();

    socket.close();
    socket.send("moves", "late");

    expect(sockets[0].sent).toEqual([]);
  });

  test("holds nothing once closed", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    socket.send("moves", "before");

    socket.close();
    socket.send("moves", "after");

    expect(socket._pending).toEqual([]);
  });

  test("holds nothing once the connection is refused", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    socket.onRefused(() => {});
    socket.send("moves", "before");

    sockets[0].onclose({ code: 1008, reason: "unknown participant" });
    socket.send("moves", "after");

    expect(socket._pending).toEqual([]);
  });
});

describe("receiving", () => {
  function opened(dallinger, options) {
    dallinger.identity.participantId = 7;
    const socket = dallinger.openChatSocket(options);
    const broadcasts = [];
    const directs = [];
    socket.onDirect((data, payload) => directs.push([data, payload]));
    if (options && options.channel) {
      socket.onBroadcast((data, payload) => broadcasts.push([data, payload]));
    }
    sockets[0].onopen();
    return { broadcasts, directs };
  }

  test("passes a message on the socket's channel to onBroadcast, parsed", () => {
    const { broadcasts, directs } = opened(load(), { channel: "room" });

    sockets[0].onmessage({ data: 'room:{"type":"hello"}' });

    expect(broadcasts).toEqual([[{ type: "hello" }, '{"type":"hello"}']]);
    expect(directs).toEqual([]);
  });

  test("passes a directed message to onDirect only", () => {
    const { broadcasts, directs } = opened(load(), { channel: "room" });

    sockets[0].onmessage({ data: 'dallinger_direct:{"type":"hello"}' });

    expect(directs).toEqual([[{ type: "hello" }, '{"type":"hello"}']]);
    expect(broadcasts).toEqual([]);
  });

  test("ignores a message on any other channel", () => {
    const { broadcasts, directs } = opened(load(), { channel: "room" });

    sockets[0].onmessage({ data: 'roomy:{"type":"hello"}' });

    expect(broadcasts).toEqual([]);
    expect(directs).toEqual([]);
  });

  test("passes a payload that is not JSON as the string itself", () => {
    const { broadcasts } = opened(load(), { channel: "room" });

    sockets[0].onmessage({ data: "room:hello there" });

    expect(broadcasts).toEqual([["hello there", "hello there"]]);
  });

  test("matches a channel name containing a colon in full", () => {
    const { broadcasts } = opened(load(), { channel: "game:7" });

    sockets[0].onmessage({ data: 'game:7:{"move":1}' });

    expect(broadcasts).toEqual([[{ move: 1 }, '{"move":1}']]);
  });

  test("refuses onBroadcast on a socket with no channel", () => {
    const socket = load().openExperimentSocket();

    expect(() => socket.onBroadcast(() => {})).toThrow();
  });

  test("refuses onDirect on a socket with no participant", () => {
    const socket = load().openChatSocket({ channel: "room" });

    expect(() => socket.onDirect(() => {})).toThrow();
  });

  test("refuses to subscribe to a reserved channel", () => {
    const dallinger = load();

    expect(() => dallinger.openChatSocket({ channel: "dallinger_direct" })).toThrow();
    expect(sockets).toHaveLength(0);
  });
});

describe("open callbacks", () => {
  test("run on every open, and say whether it was a reconnect", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    const opens = [];
    socket.onOpen((event) => opens.push(event.isReconnect));

    sockets[0].onopen();
    reconnect().onopen();

    expect(opens).toEqual([false, true]);
  });
});

describe("a refusal", () => {
  test("is reported to onRefused with its code and reason", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    const refusals = [];
    socket.onRefused((code, reason) => refusals.push([code, reason]));

    sockets[0].onclose({ code: 1008, reason: "unknown participant" });

    expect(refusals).toEqual([[1008, "unknown participant"]]);
  });

  test("is logged when nothing is listening for it", () => {
    const dallinger = load();
    const error = jest.spyOn(console, "error").mockImplementation(() => {});
    dallinger.openExperimentSocket();

    sockets[0].onclose({ code: 1008, reason: "unknown participant" });

    expect(error).toHaveBeenCalledTimes(1);
    expect(error.mock.calls[0][0]).toContain("unknown participant");
    error.mockRestore();
  });
});

describe("closing", () => {
  test("resolves once an open connection has closed", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    sockets[0].onopen();

    const closing = socket.close();
    expect(closing.state()).toBe("pending");
    expect(sockets[0].closedWith).not.toBeNull();

    sockets[0].onclose({ code: 1000, reason: "" });
    expect(closing.state()).toBe("resolved");
  });

  test("resolves at once when the connection is not open", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    sockets[0].onopen();
    sockets[0].onclose({ code: 1006, reason: "" });

    expect(socket.close().state()).toBe("resolved");
  });

  test("cancels a reconnect that was already scheduled", () => {
    const dallinger = load();
    const socket = dallinger.openExperimentSocket();
    sockets[0].onopen();
    sockets[0].onclose({ code: 1006, reason: "" });

    socket.close();
    jest.advanceTimersByTime(120000);

    expect(sockets).toHaveLength(1);
  });
});

describe("waitForQuorum", () => {
  test("follows the quorum channel until it is full", () => {
    document.body.innerHTML =
      '<div id="waiting-progress-bar"></div><span id="progress-percentage"></span>';
    const dallinger = load();

    const waiting = dallinger.waitForQuorum();
    sockets[0].onopen();
    expect(query(sockets[0]).get("channel")).toBe("quorum");

    sockets[0].onmessage({ data: 'quorum:{"n":1,"q":2}' });
    expect(document.getElementById("progress-percentage").textContent).toBe("50%");
    expect(waiting.state()).toBe("pending");

    sockets[0].onmessage({ data: 'quorum:{"n":2,"q":2}' });
    expect(waiting.state()).toBe("resolved");
  });
});
