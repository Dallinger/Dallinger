"""Handles relaying websocket messages between processes using redis."""

import json
import os
import socket

import gevent
from flask import request
from flask_sock import Sock
from gevent.lock import Semaphore
from simple_websocket import ConnectionClosed

from dallinger.db import redis_conn

from .experiment_server import app

sock = Sock(app)

# Send a ping on the websocket channel every 25 seconds
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}

CONTROL_CHANNEL = "dallinger_control"


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

    def listen(self):
        """Relay messages from a redis pubsub to all subscribed clients.

        This is run continuously in a separate greenlet. Only this greenlet
        uses the pubsub, and it closes the pubsub when the channel is stopped.
        """
        while True:
            pubsub = redis_conn.pubsub()
            try:
                pubsub.subscribe(self.name)
                log("Listening on channel {}".format(self.name))
                for message in pubsub.listen():
                    if message["type"] == "message":
                        self._relay_to_clients(message)
                    # Yield to other greenlets without capping the relay rate.
                    gevent.sleep(0)
            except Exception:
                app.logger.exception(
                    "Lost redis channel {}; retrying.".format(self.name)
                )
            finally:
                pubsub.close()
            gevent.sleep(1)

    def _relay_to_clients(self, message):
        channel = message["channel"].decode("utf-8")
        payload = "{}:{}".format(channel, message["data"].decode("utf-8"))
        for client in self.clients:
            gevent.spawn(self._relay, client, payload)

    @staticmethod
    def _relay(client, payload):
        """Send a relayed message, ignoring a client that has just disconnected.

        ``Client.send`` already unsubscribes a closed client before raising.
        """
        try:
            client.send(payload)
        except ConnectionClosed:
            log("Dropped message for a disconnected client", level="debug")

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
        """Unsubscribe a client from all channels, stopping channels left empty.

        Stopping a channel releases its redis connection, so a process only
        holds connections for channels that currently have clients.
        """
        # Channel.unsubscribe publishes to Redis, which yields to greenlets
        # that may add channels or clients.
        for channel in list(self.channels.values()):
            if client not in channel.clients:
                continue
            channel.unsubscribe(client)
            if not channel.clients and self.channels.get(channel.name) is channel:
                del self.channels[channel.name]
                channel.stop()


# There is one chat backend per process.
chat_backend = ChatBackend()


class Client:
    """Represents a single websocket client."""

    def __init__(self, ws, lag_tolerance_secs=0.1, worker_id=None, participant_id=None):
        self.ws = ws
        self.lag_tolerance_secs = lag_tolerance_secs
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
        while self.ws.connected:
            # Sleep to prevent *constant* context-switches.
            gevent.sleep(self.lag_tolerance_secs)
            try:
                message = self.ws.receive()
            except ConnectionClosed:
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
            if message is not None:
                channel_name, data = message.split(":", 1)
                redis_conn.publish(channel_name, data)


def chat(ws):
    """Relay chat messages to and from clients."""
    lag_tolerance_secs = float(request.args.get("tolerance", 0.1))
    client = Client(
        ws,
        lag_tolerance_secs=lag_tolerance_secs,
        worker_id=request.args.get("worker_id"),
        participant_id=request.args.get("participant_id"),
    )
    client.subscribe(request.args.get("channel"))
    client.publish()


# We need to keep the function around for tests, so we apply the decorator
# manually
sock.route("/chat")(chat)
