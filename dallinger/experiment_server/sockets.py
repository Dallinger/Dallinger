"""Handles relaying websocket messages between processes using redis."""

import json
import numbers
import os
import socket
import uuid
from datetime import datetime

import gevent
from flask import request
from flask_sock import Sock
from gevent.lock import Semaphore
from redis import ConnectionError, RedisError
from redis import TimeoutError as RedisTimeoutError
from simple_websocket import ConnectionClosed
from sqlalchemy.exc import SQLAlchemyError

from dallinger import models
from dallinger.db import (
    CONTROL_CHANNEL,
    DIRECT_CHANNEL,
    RESERVED_CHANNELS,
    redis_conn,
    session,
)

from .experiment_server import Experiment, app
from .utils import date_handler

sock = Sock(app)

# Send a ping on the websocket channel every 25 seconds
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}

#: Every field an envelope carries. ``deliver_direct`` indexes all four.
ENVELOPE_FIELDS = frozenset({"participant_ids", "scope", "origin", "payload"})

_process_token = None
_process_token_pid = None


def process_token():
    """Marks the envelopes this process publishes, so its own listener does not
    deliver a second copy of what ``publish_to_participants`` has already handed
    to local clients.

    Generated on first use and again whenever the pid changes, rather than at
    import. ``StandaloneServer`` inherits gunicorn's ``load_config``, which
    reads ``gunicorn.conf.py`` from the working directory and
    ``GUNICORN_CMD_ARGS`` after Dallinger's own settings, so an experiment can
    turn on ``preload_app`` without touching Dallinger. This module is then
    imported before the fork, and a token fixed there would be shared by every
    worker, each discarding the others' envelopes as its own. A pid alone would
    collide between hosts.
    """
    global _process_token, _process_token_pid
    pid = os.getpid()
    if _process_token_pid != pid:
        _process_token = uuid.uuid4().hex
        _process_token_pid = pid
    return _process_token


#: RFC 6455 policy violation, reported to the browser as ``event.code`` on
#: ``onclose``. Dallinger's bundled ``ReconnectingWebSocket`` stops retrying on
#: it.
REFUSED_CLOSE_CODE = 1008

#: IANA "try again later". Unlike a refusal, a client should reconnect.
UNAVAILABLE_CLOSE_CODE = 1013

#: RFC 6455 unsupported data. Sent when a client frames something this
#: protocol has no way to route.
UNSUPPORTED_DATA_CLOSE_CODE = 1003

# redis-py reconnects and resubscribes the pubsub before re-raising these,
# so a later read resumes the stream. Other RedisErrors are protocol-level
# and a retry would hit the same thing.
RETRYABLE_REDIS_ERRORS = (ConnectionError, RedisTimeoutError)


def log(msg, level="info"):
    # Log including pid and greenlet id
    logfunc = getattr(app.logger, level)
    logfunc("{}/{}: {}".format(os.getpid(), id(gevent.hub.getcurrent()), msg))


_process_experiment = None
_process_experiment_lock = Semaphore()


def process_experiment():
    """The one ``Experiment`` this process hands to its experiment-socket clients.

    ``Experiment.__init__`` runs ``configure()``, which is experiment code and
    may query, so the constructor can yield and two connections would otherwise
    each build one.
    """
    global _process_experiment
    with _process_experiment_lock:
        if _process_experiment is None:
            try:
                _process_experiment = Experiment()
            finally:
                session.remove()
    return _process_experiment


def publish_control_event(payload):
    """Publish one control event, logging instead of raising if redis is down.

    Control events are notifications, and every caller is in the middle of
    bookkeeping it must finish. Raising would abort a teardown partway and
    leave a client registered on a channel whose listener retries forever.
    """
    try:
        redis_conn.publish(CONTROL_CHANNEL, json.dumps(payload))
    except RedisError:
        app.logger.exception(
            "Could not publish {} control event.".format(payload.get("event"))
        )


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
        publish_control_event(
            {
                "type": "channel",
                "event": "subscribed",
                "channel": self.name,
                "client": client.client_info(),
            }
        )

    def unsubscribe(self, client):
        """Unsubscribe a client from the channel."""
        if client in self.clients:
            self.clients.remove(client)
            log(
                "Unsubscribed client {} from channel {}".format(client, self.name),
                level="debug",
            )
            publish_control_event(
                {
                    "type": "channel",
                    "event": "unsubscribed",
                    "channel": self.name,
                    "client": client.client_info(),
                }
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

        A lost redis connection is retried without limit, and so is the
        first subscription. ``launch`` subscribes the experiment to its own
        channel and to the control channel and never unsubscribes either, so
        giving up would leave an experiment deaf until its worker restarts.
        Every other channel is bounded by ``ChatBackend.unsubscribe``, which
        stops the greenlet once the last client leaves. The full traceback is
        logged once per outage and a single line per attempt after that,
        because at the ceiling an outage otherwise writes six tracebacks a
        minute for every channel.
        """
        pubsub = redis_conn.pubsub()
        name = self.name
        if isinstance(name, str):
            name = name.encode("utf-8")
        try:
            delay = self.RECONNECT_DELAY_SECS
            reported = False
            subscribed = False
            while True:
                try:
                    if not subscribed:
                        # redis-py records the subscription only once the
                        # command succeeds, and replays it itself on every
                        # later reconnect.
                        pubsub.subscribe([name])
                        subscribed = True
                        log("Listening on channel {}".format(self.name))
                    for message in pubsub.listen():
                        self.relay(message)
                        if message["type"] == "message":
                            # redis-py resubscribes on every reconnect, so a
                            # confirmation frame arrives while the connection
                            # is still flapping. Only traffic proves recovery.
                            delay = self.RECONNECT_DELAY_SECS
                            reported = False
                        # ``relay`` only spawns senders, and messages already
                        # in the socket buffer are read without blocking, so
                        # nothing else here hands the hub back.
                        gevent.sleep(0)
                except RETRYABLE_REDIS_ERRORS:
                    template = (
                        "Lost redis connection on channel {}, retrying in {}s."
                        if subscribed
                        else "Could not subscribe to channel {}, retrying in {}s."
                    )
                    if reported:
                        app.logger.warning(template.format(self.name, delay))
                    else:
                        app.logger.exception(template.format(self.name, delay))
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
            chat_backend.forget(self)

    def start(self):
        """Start relaying messages."""
        self.greenlet = gevent.spawn(self.listen)

    def stop(self):
        """Stop relaying messages."""
        if self.greenlet:
            self.greenlet.kill()
            self.greenlet = None


class DirectChannel(Channel):
    """Relays directed sends published by other processes to local clients.

    A process runs one of these while it holds any connection that named a
    participant. It has no subscribers of its own: an envelope names
    participants, and the backend looks up their connections, so a client is
    addressable without having subscribed to anything.
    """

    def __init__(self, backend):
        super().__init__(DIRECT_CHANNEL)
        self.backend = backend

    def relay(self, message):
        """Hand one envelope to the backend, unless this process published it."""
        if message["type"] != "message":
            return
        envelope = parsed_envelope(message.get("data"))
        if envelope is None:
            log(
                "Discarding an unreadable envelope on the {} channel.".format(
                    self.name
                ),
                level="warning",
            )
            return
        if envelope["origin"] == process_token():
            return
        self.backend.deliver_direct(envelope)


def parsed_envelope(data):
    """The directed send ``data`` carries, or ``None`` if it carries no envelope.

    Every field ``deliver_direct`` reads is checked here, because this is where
    an envelope enters the process. Clients cannot publish to the channel, but
    :func:`~dallinger.experiment.Experiment.publish_to_subscribers` names
    whichever channel it is given and anything else holding the redis
    credentials can publish too. An exception raised in a relay unwinds
    ``Channel.listen``, which catches redis errors only, and the process is
    then left with no listener until its next addressable connection.

    A participant id has to be a string because it is looked up as a dict key,
    and an unhashable one raises rather than missing.
    """
    try:
        envelope = json.loads(data)
    except (TypeError, ValueError):
        return None
    if not isinstance(envelope, dict) or not ENVELOPE_FIELDS <= envelope.keys():
        return None
    if not isinstance(envelope["origin"], str):
        return None
    if not isinstance(envelope["payload"], str):
        return None
    if envelope["scope"] is not None and not isinstance(envelope["scope"], str):
        return None
    if not isinstance(envelope["participant_ids"], list):
        return None
    if not all(isinstance(each, str) for each in envelope["participant_ids"]):
        return None
    return envelope


class ChatBackend:
    """Manages subscriptions of clients to multiple channels."""

    def __init__(self):
        self.channels = {}
        #: Addressable participant id -> the clients on this process that
        #: named it. A participant can hold several at once: a page that opens
        #: both websocket routes, or a reload that connects before the old
        #: socket times out.
        self.clients_by_participant = {}
        self.direct_channel = None

    def subscribe(self, client, channel_name):
        """Register a new client to receive messages on a channel."""
        if channel_name not in self.channels:
            self.channels[channel_name] = channel = Channel(channel_name)
            channel.start()

        self.channels[channel_name].subscribe(client)

    def unsubscribe(self, client):
        """Unsubscribe a client from all channels and stop addressing it.

        A channel left with no clients stops listening and is dropped.
        """
        self.deregister(client)
        for name, channel in list(self.channels.items()):
            channel.unsubscribe(client)
            # ``Greenlet.kill`` blocks, so ``stop()`` reaches the hub: drop
            # the channel first, or a subscribe in that window attaches to it.
            if not channel.clients and self.channels.get(name) is channel:
                del self.channels[name]
                channel.stop()

    def register(self, client):
        """Make a client reachable by the participant id it named.

        A connection that named no usable id is left unaddressable rather
        than refused: it can still subscribe, send, and receive broadcasts.
        """
        addressable_id = getattr(client, "addressable_id", None)
        if addressable_id is None:
            return
        self.clients_by_participant.setdefault(addressable_id, set()).add(client)
        if self.direct_channel is None:
            self.direct_channel = DirectChannel(self)
            self.direct_channel.start()

    def deregister(self, client):
        """Stop addressing a client.

        The listener is left running once started. Stopping it with the last
        addressable client and starting it again with the next costs a window,
        during ``Greenlet.kill``, in which a registration either attaches to a
        dying listener and is never reached, or starts a second one that
        delivers the same envelope twice. One idle subscription is cheaper than
        either.
        """
        addressable_id = getattr(client, "addressable_id", None)
        clients = self.clients_by_participant.get(addressable_id)
        if clients is None:
            return
        clients.discard(client)
        if not clients:
            del self.clients_by_participant[addressable_id]

    def deliver_direct(self, envelope):
        """Send one directed payload to this process's matching connections.

        An envelope carrying a ``scope`` reaches only the connections opened
        with that same scope. Every process sees every envelope, so naming
        participants who are connected elsewhere, or nowhere, is ordinary.
        """
        scope = envelope["scope"]
        frame = "{}:{}".format(DIRECT_CHANNEL, envelope["payload"])
        for participant_id in envelope["participant_ids"]:
            for client in list(self.clients_by_participant.get(participant_id, ())):
                if scope is not None and client.scope != scope:
                    continue
                gevent.spawn(client.send, frame)

    def forget(self, channel):
        """Drop a channel whose listener has stopped.

        The listening greenlet calls this as it exits, so a later subscriber
        builds a channel with a live listener instead of attaching to a dead
        one. The identity check keeps a replacement already registered under
        the same name.
        """
        if self.direct_channel is channel:
            self.direct_channel = None
            return
        if self.channels.get(channel.name) is channel:
            del self.channels[channel.name]


# There is one chat backend per process.
chat_backend = ChatBackend()


class Client:
    """Represents a single websocket client.

    A client holding an ``experiment`` hands it each inbound message. One
    without publishes to redis for a subscriber to pick up.
    """

    def __init__(
        self,
        ws,
        worker_id=None,
        participant_id=None,
        scope=None,
        experiment=None,
    ):
        self.ws = ws
        self.worker_id = worker_id
        self.participant_id = participant_id
        self.addressable_id = normalized_participant_id(participant_id)
        self.scope = scope
        self.experiment = experiment

        # This lock is used to make sure that multiple greenlets
        # cannot send to the same socket concurrently.
        self.send_lock = Semaphore()

    def client_info(self):
        return {
            "class": self.__class__.__module__ + "." + self.__class__.__name__,
            "worker_id": self.worker_id,
            "participant_id": self.participant_id,
            "scope": self.scope,
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
                publish_control_event(
                    {
                        "type": "websocket",
                        "event": "disconnected",
                        "reason": self.ws.close_reason or "",
                        "message": self.ws.close_message or "",
                        "client": self.client_info(),
                    }
                )
                if isinstance(e, ConnectionClosed):
                    raise
                raise ConnectionClosed(self.ws.close_reason, self.ws.close_message)
            # log('Sent to {}: {}'.format(self, message), level='debug')

    def subscribe(self, channel):
        """Start listening to messages on ``channel``, if there is one.

        A connection may name no channel, in which case it receives nothing
        and only sends. Subscribing to the empty name would build a channel
        redis refuses to subscribe to. A name in ``RESERVED_CHANNELS`` is
        refused.
        """
        if not channel:
            return
        if channel in RESERVED_CHANNELS:
            log(
                "Client {} may not subscribe to the reserved channel {}.".format(
                    self.client_info(), channel
                ),
                level="warning",
            )
            return
        chat_backend.subscribe(self, channel)

    def publish(self):
        """Read messages from the client until the connection closes."""
        try:
            # Inside the ``finally`` below: ``_serve()`` has already subscribed
            # the client, so everything from here on needs teardown.
            publish_control_event(
                {
                    "type": "websocket",
                    "event": "connected",
                    "client": self.client_info(),
                }
            )
            while self.ws.connected:
                try:
                    # ``receive()`` waits on a ``threading.Event``, which gevent
                    # patches, so this loop yields to the hub here.
                    message = self.ws.receive()
                except ConnectionClosed:
                    self.publish_disconnected(
                        self.ws.close_reason or "", self.ws.close_message or ""
                    )
                    raise
                if message is None:
                    continue
                if not isinstance(message, str):
                    # A binary frame has no channel prefix to split on, so
                    # there is nowhere to route it.
                    log(
                        "Closing connection from {} after a binary frame.".format(
                            self.client_info()
                        ),
                        level="warning",
                    )
                    with self.send_lock:
                        self.ws.close(UNSUPPORTED_DATA_CLOSE_CODE, "text frames only")
                    self.publish_disconnected(
                        UNSUPPORTED_DATA_CLOSE_CODE, "text frames only"
                    )
                    return
                channel_name, separator, data = message.partition(":")
                if not separator or not channel_name:
                    log(
                        "Discarding message with no channel prefix: {}".format(message),
                        level="warning",
                    )
                    continue
                if channel_name in RESERVED_CHANNELS:
                    log(
                        "Client {} may not publish to the reserved channel {}.".format(
                            self.client_info(), channel_name
                        ),
                        level="warning",
                    )
                    continue
                if self.experiment is not None:
                    self.handle(channel_name, data)
                else:
                    redis_conn.publish(channel_name, data)
        finally:
            chat_backend.unsubscribe(self)

    def publish_disconnected(self, reason, message=""):
        """Unsubscribe and announce that this connection is over.

        ``reason`` is the numeric close code and ``message`` the text, matching
        ``simple_websocket``, where ``close_reason`` holds ``event.code``
        despite its name.

        Unsubscribing first puts the "unsubscribed" control message ahead of
        the "disconnected" one; subscribers rely on that order. ``publish()``
        unsubscribes again in its ``finally``, which is a no-op by then.
        """
        chat_backend.unsubscribe(self)
        publish_control_event(
            {
                "type": "websocket",
                "event": "disconnected",
                "reason": reason,
                "message": message,
                "client": self.client_info(),
            }
        )

    def handle(self, channel_name, data):
        """Pass one frame to the experiment running in this process.

        The session is removed afterwards so the next frame starts with an
        empty identity map and no open transaction. Experiment code owns its
        own commits.

        Letting a handler's exception propagate would unwind ``publish()``
        and close a connection the participant's browser expects to stay open.
        """
        try:
            self.experiment.handle_websocket_message(
                data,
                channel_name=channel_name,
                participant_id=self.participant_id,
                scope=self.scope,
                # Naive local, like models.timenow(). Every Dallinger DateTime
                # column is naive, so an aware value stored in one loses its
                # offset and reads back as local.
                receive_time=datetime.now(),
            )
        except Exception:
            app.logger.exception(
                "Error handling websocket message from {}.".format(self.client_info())
            )
        finally:
            session.remove()


def publish_to_participants(payload, participant_ids, scope=None):
    """Send ``payload`` to every connection naming one of ``participant_ids``.

    Delivery is to connections, not to participants: each of a participant's
    open sockets receives a copy, wherever in the deployment it is held. The
    connections on this process are sent theirs directly, and an envelope goes
    to redis for the processes holding the rest.

    A redis failure raises, having delivered to nobody, so the caller can
    retry the whole send rather than guess which half of it landed.
    """
    if isinstance(participant_ids, (str, bytes, int)):
        participant_ids = [participant_ids]
    addressable_ids = []
    for participant_id in participant_ids:
        addressable_id = normalized_participant_id(participant_id)
        if addressable_id is None:
            log(
                "Cannot address a directed send to {!r}.".format(participant_id),
                level="warning",
            )
        elif addressable_id not in addressable_ids:
            addressable_ids.append(addressable_id)
    if not addressable_ids:
        return
    envelope = {
        "participant_ids": addressable_ids,
        # A connection names its scope in a query string, so the value it is
        # compared against is text on that side whatever the caller passed.
        "scope": None if scope is None else str(scope),
        "origin": process_token(),
        # Serialized here so that every recipient of one send is delivered the
        # same bytes.
        "payload": json.dumps(payload, default=date_handler),
    }
    # Published first: ``deliver_direct`` only spawns senders, so the order
    # costs nothing, and a redis failure then reaches nobody rather than
    # leaving this process's connections served and every other process's not.
    redis_conn.publish(DIRECT_CHANNEL, json.dumps(envelope))
    chat_backend.deliver_direct(envelope)


def normalized_participant_id(participant_id):
    """The string form of the participant id ``participant_id`` names, or ``None``.

    The id comes back as a string, which is the form every other Dallinger
    route carries it in. It is the parsed value rendered back rather than the
    value passed in, because ``int()`` accepts more than the column does,
    including surrounding whitespace, a leading sign, and non-ASCII decimal
    digits. Passing the raw string on would let a lookup succeed and then raise
    ``DataError`` on every later query.

    Only text and whole numbers are parsed. ``int()`` would read ``12.7`` as
    participant 12 and ``True`` as participant 1, so a value that is neither a
    string nor an integer is refused rather than truncated. ``numbers.Integral``
    rather than ``int`` so that a numpy integer, which a caller reading ids out
    of a dataframe column has, is a whole number here too.
    """
    if isinstance(participant_id, bool) or not isinstance(
        participant_id, (str, bytes, numbers.Integral)
    ):
        return None
    try:
        return str(int(participant_id))
    except ValueError:
        return None


def resolve_participant_id(participant_id):
    """The id of the participant ``participant_id`` names, or ``None``.

    Existence is checked against the normalized id, so a value the column
    cannot hold is refused before a query is made with it.
    """
    normalized = normalized_participant_id(participant_id)
    if normalized is None:
        return None
    try:
        found = (
            session.query(models.Participant.id).filter_by(id=int(normalized)).scalar()
            is not None
        )
    finally:
        session.remove()
    return normalized if found else None


def _serve(ws, participant_id=None, experiment=None):
    """Subscribe a connection to its channel and relay until it closes."""
    client = Client(
        ws,
        worker_id=request.args.get("worker_id"),
        participant_id=participant_id,
        scope=request.args.get("scope"),
        experiment=experiment,
    )
    client.subscribe(request.args.get("channel"))
    chat_backend.register(client)
    client.publish()


def chat(ws):
    """Relay messages between a client and redis."""
    _serve(ws, participant_id=request.args.get("participant_id"))


def experiment_socket(ws):
    """Hand each inbound message to the experiment running in this process."""
    requested_id = request.args.get("participant_id")
    try:
        participant_id = resolve_participant_id(requested_id)
    except SQLAlchemyError:
        log(
            "Could not look up participant {!r} for an experiment socket.".format(
                requested_id
            ),
            level="exception",
        )
        ws.close(UNAVAILABLE_CLOSE_CODE, "participant lookup failed")
        return
    # handle_websocket_message is told which participant sent each message, so
    # a connection we cannot name is refused rather than handled anonymously.
    # Existence is all this proves: the route is unauthenticated, so the id is
    # not evidence of who is on the other end.
    if participant_id is None:
        log(
            "Refusing experiment socket for unknown participant {!r}.".format(
                requested_id
            ),
            level="warning",
        )
        ws.close(REFUSED_CLOSE_CODE, "unknown participant")
        return
    try:
        experiment = process_experiment()
    except Exception:
        log("Could not build the experiment.", level="exception")
        ws.close(UNAVAILABLE_CLOSE_CODE, "experiment unavailable")
        return
    _serve(ws, participant_id=participant_id, experiment=experiment)


# We need to keep the functions around for tests, so we apply the decorators
# manually
sock.route("/chat")(chat)
sock.route("/experiment-socket")(experiment_socket)
