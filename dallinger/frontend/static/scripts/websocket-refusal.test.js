/*globals expect, describe, jest, test, beforeEach, afterEach */

// dallinger.stopReconnectingIfRefused against the real ReconnectingWebSocket,
// whose reconnect timer and event shapes are what the helper works around.

// dallinger2's _initialize() alerts on load under jsdom.
global.window.alert = () => {};

let sockets;

class StubWebSocket {
  constructor(url) {
    this.url = url;
    sockets.push(this);
  }
  close() {}
  send() {}
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
  return {
    ReconnectingWebSocket,
    dallinger: require("./dallinger2").dallinger,
  };
}

beforeEach(() => {
  jest.useFakeTimers();
  sockets = [];
});

afterEach(() => {
  jest.useRealTimers();
});

describe("a refused connection", () => {
  test("is not retried", () => {
    const { ReconnectingWebSocket, dallinger } = load();
    const socket = new ReconnectingWebSocket("ws://localhost/experiment-socket");
    dallinger.stopReconnectingIfRefused(socket);
    expect(sockets).toHaveLength(1);

    sockets[0].onclose({ code: 1008, reason: "unknown participant" });
    jest.advanceTimersByTime(120000);

    expect(sockets).toHaveLength(1);
  });

  test("reports its code and reason to the callback", () => {
    const { ReconnectingWebSocket, dallinger } = load();
    const socket = new ReconnectingWebSocket("ws://localhost/experiment-socket");
    const refusals = [];
    dallinger.stopReconnectingIfRefused(socket, (code, reason) => {
      refusals.push([code, reason]);
    });

    sockets[0].onclose({ code: 1008, reason: "unknown participant" });

    expect(refusals).toEqual([[1008, "unknown participant"]]);
  });

  test("leaves the socket closed rather than connecting", () => {
    const { ReconnectingWebSocket, dallinger } = load();
    const socket = new ReconnectingWebSocket("ws://localhost/experiment-socket");
    dallinger.stopReconnectingIfRefused(socket);

    sockets[0].onclose({ code: 1008, reason: "unknown participant" });
    jest.advanceTimersByTime(120000);

    expect(socket.readyState).toBe(StubWebSocket.CLOSED);
  });
});

describe("any other close", () => {
  test("still reconnects", () => {
    const { ReconnectingWebSocket, dallinger } = load();
    const socket = new ReconnectingWebSocket("ws://localhost/experiment-socket");
    dallinger.stopReconnectingIfRefused(socket);

    sockets[0].onclose({ code: 1013, reason: "participant lookup failed" });
    jest.advanceTimersByTime(120000);

    expect(sockets.length).toBeGreaterThan(1);
  });

  test("leaves the socket connecting", () => {
    const { ReconnectingWebSocket, dallinger } = load();
    const socket = new ReconnectingWebSocket("ws://localhost/chat");
    dallinger.stopReconnectingIfRefused(socket);

    sockets[0].onclose({ code: 1013, reason: "participant lookup failed" });

    expect(socket.readyState).toBe(StubWebSocket.CONNECTING);
  });
});
