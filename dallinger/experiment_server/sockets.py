from collections import defaultdict
from .experiment_server import app
from ..heroku.worker import conn
from flask import request
from flask_sockets import Sockets
from redis import ConnectionError
import gevent
import os
import socket

sockets = Sockets(app)

HEARTBEAT_DELAY = 30


def log(msg, level='info'):
    # Log including pid and greenlet id
    logfunc = getattr(app.logger, level)
    logfunc(
        '{}/{}: {}'.format(os.getpid(), id(gevent.hub.getcurrent()), msg))


class ChatBackend(object):
    """Chat backend which relays messages from a redis pubsub to clients.

    This is run by each web process; all processes receive the messages.

    Inspired by https://devcenter.heroku.com/articles/python-websockets
    """

    def __init__(self):
        self.pubsub = conn.pubsub()
        self.clients = defaultdict(list)
        self.greenlet = None

    def subscribe(self, client, channel):
        """Register a new client to receive messages on a channel."""

        # Make sure this process is subscribed to the redis channel
        if channel not in self.pubsub.channels:
            try:
                self.pubsub.subscribe([channel])
            except ConnectionError:
                app.logger.exception('Could not connect to redis.')
            else:
                log('Subscribed to redis channel {}'.format(channel))

        # Make sure this process has a greenlet listening for messages
        if self.greenlet is None:
            self.start()

        self.clients[channel].append(client)
        log('Subscribed client {} to channel {}'.format(client, channel))

    def unsubscribe(self, client, channel):
        if client in self.clients[channel]:
            self.clients[channel].remove(client)
            log('Removed client {} from channel {}'.format(client, channel))

    def send(self, client, data):
        """Send data to one client.

        Automatically discards invalid connections.
        """
        try:
            client.send(data.decode('utf-8'))
        except socket.error:
            for channel in self.clients:
                self.unsubscribe(client, channel)
        else:
            log('Sent to {}: {}'.format(client, data), level='debug')

    def run(self):
        """Listens for new messages in redis, and sends them to clients."""
        log('Listening for messages')
        for message in self.pubsub.listen():
            data = message.get('data')
            if message['type'] == 'message' and data != 'None':
                channel = message['channel']
                count = len(self.clients[channel])
                if count:
                    for client in self.clients[channel]:
                        gevent.spawn(
                            self.send, client, '{}:{}'.format(channel, data))

    def start(self):
        """Starts listening in the background."""
        self.greenlet = gevent.spawn(self.run)

    def stop(self):
        if self.greenlet is not None:
            self.greenlet.kill()
            self.greenlet = None

    def heartbeat(self, ws):
        """Send a ping to the websocket client periodically"""
        while not ws.closed:
            gevent.sleep(HEARTBEAT_DELAY)
            gevent.spawn(self.send, ws, 'ping')


chat_backend = ChatBackend()


@sockets.route('/chat')
def chat(ws):
    """Relay chat messages to and from clients.
    """
    # Subscribe to messages on the specified channel.
    channel = request.args.get('channel')
    lag_tolerance_secs = float(request.args.get('tolerance', 0.1))
    chat_backend.subscribe(ws, channel)

    # Send heartbeat ping every 30s
    # so Heroku won't close the connection
    gevent.spawn(chat_backend.heartbeat, ws)

    while not ws.closed:
        # Sleep to prevent *constant* context-switches.
        gevent.sleep(lag_tolerance_secs)

        # Publish messages from client
        message = ws.receive()
        if message is not None:
            channel, data = message.split(':', 1)
            conn.publish(channel, data)
