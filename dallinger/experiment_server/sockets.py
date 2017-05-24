from collections import defaultdict
from .experiment_server import app
from .experiment_server import WAITING_ROOM_CHANNEL
from ..heroku.worker import conn
from flask import request
from flask_sockets import Sockets
from redis import ConnectionError
import gevent
import socket

sockets = Sockets(app)

DEFAULT_CHANNELS = [
    WAITING_ROOM_CHANNEL,
]
HEARTBEAT_DELAY = 30


class ChatBackend(object):
    """Chat backend which relays messages from a redis pubsub to clients.

    This is run by each web process; all processes receive the messages.

    Inspired by https://devcenter.heroku.com/articles/python-websockets
    """

    def __init__(self):
        self.pubsub = conn.pubsub()
        self._join_pubsub(DEFAULT_CHANNELS)
        self.clients = defaultdict(list)

    def _join_pubsub(self, channels):
        try:
            self.pubsub.subscribe(channels)
            app.logger.debug(
                'Subscribed to channels: {}'.format(self.pubsub.channels.keys())
            )
        except ConnectionError:
            app.logger.exception('Could not connect to redis.')

    def subscribe(self, client, channel=None):
        """Register a new client to receive messages."""
        if channel is not None:
            self.clients[channel].append(client)
            if channel not in self.pubsub.channels:
                self._join_pubsub([channel])
        else:
            for channel in DEFAULT_CHANNELS:
                self.clients[channel].append(client)
                app.logger.debug(
                    'Subscribed client {} to channel {}'.format(
                        client, channel))

    def unsubscribe(self, client, channel):
        if client in self.clients[channel]:
            self.clients[channel].remove(client)

    def send(self, client, data):
        """Send data to one client.

        Automatically discards invalid connections.
        """
        try:
            client.send(data)
        except socket.error:
            for channel in self.clients:
                self.unsubscribe(client, channel)

    def run(self):
        """Listens for new messages in redis, and sends them to clients."""
        for message in self.pubsub.listen():
            data = message.get('data')
            if message['type'] == 'message' and data != 'None':
                channel = message['channel']
                count = len(self.clients[channel])
                if count:
                    app.logger.debug(
                        'Relaying message on channel {} to {} clients: {}'.format(
                            channel, len(self.clients[channel]), data))
                    for client in self.clients[channel]:
                        gevent.spawn(
                            self.send, client, '{}:{}'.format(channel, data))

    def start(self):
        """Starts listening in the background."""
        self.greenlet = gevent.spawn(self.run)

    def stop(self):
        self.greenlet.kill()

    def heartbeat(self, ws):
        """Send a ping to the websocket client periodically"""
        while not ws.closed:
            gevent.sleep(HEARTBEAT_DELAY)
            gevent.spawn(self.send, ws, 'ping')


chat_backend = ChatBackend()
app.before_first_request(chat_backend.start)


@sockets.route('/chat')
def chat(ws):
    """Relay chat messages to and from clients.
    """
    # Subscribe to messages on the specified channel.
    chat_backend.subscribe(ws, channel=request.args.get('channel'))

    # Send heartbeat ping every 30s
    # so Heroku won't close the connection
    gevent.spawn(chat_backend.heartbeat, ws)

    while not ws.closed:
        # Sleep to prevent *constant* context-switches.
        gevent.sleep(0.1)

        # Publish messages from client
        message = ws.receive()
        if message is not None:
            channel, data = message.split(':', 1)
            conn.publish(channel, data)
