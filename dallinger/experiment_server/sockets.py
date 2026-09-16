"""Handles relaying websocket messages between processes using redis."""

import json
import os
import socket

import gevent
from flask import request
from flask_sock import Sock
from gevent.lock import Semaphore
from redis import ConnectionError, RedisError
from redis import TimeoutError as RedisTimeoutError
from simple_websocket import ConnectionClosed

from dallinger.db import redis_conn

from .experiment_server import app

sock = Sock(app)

# Send a ping on the websocket channel every 25 seconds
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}

CONTROL_CHANNEL = "dallinger_control"

# redis-py reconnects and resubscribes the pubsub before re-raising these,
# so a later read resumes the stream. Other RedisErrors are protocol-level
# and a retry would hit the same thing.
RETRYABLE_REDIS_ERRORS = (ConnectionError, RedisTimeoutError)


def log(msg, level="info"):
    # Log including pid and greenlet id
    logfunc = getattr(app.logger, level)
    logfunc("{}/{}: {}".format(os.getpid(), id(gevent.hub.getcurrent()), msg))


class Channel:
    """A channel relays messages from a redis pubsub to multiple clients.

    Creating a channel spawns a greenlet which listens for messages from redis
    on the specified channel name.

    When a message is received, it is relayed to all clients that have subscribed.
    """

    #: Seconds to wait before re-reading after a lost redis connection,
    #: doubling on each consecutive failure up to the maximum.
    RECONNECT_DELAY_SECS = 0.5
    MAX_RECONNECT_DELAY_SECS = 10

    def __init__(self, name):
        self.name = name
        self.clients = []
        self.greenlet = None

    def subscribe(self, client):
        """Subscribe a client to the channel."""
        self.clients.append(client)
        log(
            "Subscribed client {} to channel {}".format(client, self.name),
            level="debug",
        )
        redis_conn.publish(
            CONTROL_CHANNEL,
            json.dumps(
                {
                    "type": "channel",
                    "event": "subscribed",
                    "channel": self.name,
                    "client": client.client_info(),
                }
            ),
        )

    def unsubscribe(self, client):
        """Unsubscribe a client from the channel."""
        if client in self.clients:
            self.clients.remove(client)
            log(
                "Unsubscribed client {} from channel {}".format(client, self.name),
                level="debug",
            )
            redis_conn.publish(
                CONTROL_CHANNEL,
                json.dumps(
                    {
                        "type": "channel",
                        "event": "unsubscribed",
                        "channel": self.name,
                        "client": client.client_info(),
                    }
                ),
            )

    def relay(self, message):
        """Send one pubsub message to every subscribed client."""
        data = message.get("data")
        if message["type"] != "message" or data == "None":
            return
        payload = "{}:{}".format(
            message["channel"].decode("utf-8"), data.decode("utf-8")
        )
        for client in self.clients:
            gevent.spawn(client.send, payload)

    def listen(self):
        """Relay messages from a redis pubsub to all subscribed clients.

        This is run continuously in a separate greenlet.

        A lost redis connection is retried without limit. ``launch``
        subscribes the experiment to its own channel and to the control
        channel and never unsubscribes either, so giving up would leave an
        experiment deaf until its worker restarts. Every other channel is
        bounded by ``ChatBackend.unsubscribe``, which stops the greenlet once
        the last client leaves. The full traceback is logged once per outage
        and a single line per attempt after that, because at the ceiling an
        outage otherwise writes six tracebacks a minute for every channel.
        """
        pubsub = redis_conn.pubsub()
        name = self.name
        if isinstance(name, str):
            name = name.encode("utf-8")
        try:
            try:
                pubsub.subscribe([name])
            except RedisError:
                app.logger.exception(
                    "Could not subscribe to channel {}.".format(self.name)
                )
                return
            log("Listening on channel {}".format(self.name))
            delay = self.RECONNECT_DELAY_SECS
            reported = False
            while True:
                try:
                    for message in pubsub.listen():
                        self.relay(message)
                        delay = self.RECONNECT_DELAY_SECS
                        reported = False
                except RETRYABLE_REDIS_ERRORS:
                    message = "Lost redis connection on channel {}, retrying in {}s."
                    if reported:
                        app.logger.warning(message.format(self.name, delay))
                    else:
                        app.logger.exception(message.format(self.name, delay))
                        reported = True
                    gevent.sleep(delay)
                    delay = min(delay * 2, self.MAX_RECONNECT_DELAY_SECS)
                except RedisError:
                    app.logger.exception(
                        "Unrecoverable redis error on channel {}.".format(self.name)
                    )
                    return
                else:
                    return
        finally:
            # Returns the connection to the redis pool. ``stop()`` reaches this
            # too, because killing a greenlet raises inside it.
            pubsub.close()

    def start(self):
        """Start relaying messages."""
        self.greenlet = gevent.spawn(self.listen)

    def stop(self):
        """Stop relaying messages."""
        if self.greenlet:
            self.greenlet.kill()
            self.greenlet = None


class ChatBackend:
    """Manages subscriptions of clients to multiple channels."""

    def __init__(self):
        self.channels = {}

    def subscribe(self, client, channel_name):
        """Register a new client to receive messages on a channel."""
        if channel_name not in self.channels:
            self.channels[channel_name] = channel = Channel(channel_name)
            channel.start()

        self.channels[channel_name].subscribe(client)

    def unsubscribe(self, client):
        """Unsubscribe a client from all channels.

        A channel left with no clients stops listening and is dropped.
        """
        for name, channel in list(self.channels.items()):
            channel.unsubscribe(client)
            # ``Greenlet.kill`` blocks, so ``stop()`` reaches the hub: drop
            # the channel first, or a subscribe in that window attaches to it.
            if not channel.clients and self.channels.get(name) is channel:
                del self.channels[name]
                channel.stop()


# There is one chat backend per process.
chat_backend = ChatBackend()


class Client:
    """Represents a single websocket client."""

    def __init__(self, ws, worker_id=None, participant_id=None):
        self.ws = ws
        self.worker_id = worker_id
        self.participant_id = participant_id

        # This lock is used to make sure that multiple greenlets
        # cannot send to the same socket concurrently.
        self.send_lock = Semaphore()

    def client_info(self):
        return {
            "class": self.__class__.__module__ + "." + self.__class__.__name__,
            "worker_id": self.worker_id,
            "participant_id": self.participant_id,
        }

    def send(self, message):
        """Send a single message to the websocket."""
        if isinstance(message, bytes):
            message = message.decode("utf8")

        with self.send_lock:
            try:
                self.ws.send(message)
            except (socket.error, ConnectionClosed) as e:
                chat_backend.unsubscribe(self)
                redis_conn.publish(
                    CONTROL_CHANNEL,
                    json.dumps(
                        {
                            "type": "websocket",
                            "event": "disconnected",
                            "reason": self.ws.close_reason or "",
                            "message": self.ws.close_message or "",
                            "client": self.client_info(),
                        }
                    ),
                )
                if isinstance(e, ConnectionClosed):
                    raise
                raise ConnectionClosed(self.ws.close_reason, self.ws.close_message)
            # log('Sent to {}: {}'.format(self, message), level='debug')

    def subscribe(self, channel):
        """Start listening to messages on the specified channel."""
        chat_backend.subscribe(self, channel)

    def publish(self):
        """Relay messages from client to redis."""
        redis_conn.publish(
            CONTROL_CHANNEL,
            json.dumps(
                {
                    "type": "websocket",
                    "event": "connected",
                    "client": self.client_info(),
                }
            ),
        )
        try:
            while self.ws.connected:
                try:
                    # ``receive()`` waits on a ``threading.Event``, which gevent
                    # patches, so this loop yields to the hub here.
                    message = self.ws.receive()
                except ConnectionClosed:
                    # Also unsubscribed by the ``finally`` below. It happens
                    # here so the "unsubscribed" control message precedes the
                    # "disconnected" one; subscribers rely on that order.
                    chat_backend.unsubscribe(self)
                    redis_conn.publish(
                        CONTROL_CHANNEL,
                        json.dumps(
                            {
                                "type": "websocket",
                                "event": "disconnected",
                                "reason": self.ws.close_reason or "",
                                "message": self.ws.close_message or "",
                                "client": self.client_info(),
                            }
                        ),
                    )
                    raise
                if message is None:
                    continue
                channel_name, separator, data = message.partition(":")
                if not separator or not channel_name:
                    log(
                        "Discarding message with no channel prefix: {}".format(message),
                        level="warning",
                    )
                    continue
                # The experiment subscribes to the control channel at launch
                # and dispatches what arrives there as a server-sent event, so
                # a client frame addressed to it would be acted on as genuine.
                if channel_name == CONTROL_CHANNEL:
                    log(
                        "Client {} may not publish to the control channel.".format(
                            self.client_info()
                        ),
                        level="warning",
                    )
                    continue
                redis_conn.publish(channel_name, data)
        finally:
            chat_backend.unsubscribe(self)


def chat(ws):
    """Relay chat messages to and from clients."""
    client = Client(
        ws,
        worker_id=request.args.get("worker_id"),
        participant_id=request.args.get("participant_id"),
    )
    client.subscribe(request.args.get("channel"))
    client.publish()


# We need to keep the function around for tests, so we apply the decorator
# manually
sock.route("/chat")(chat)
