Using WebSockets in Dallinger Experiments
=========================================

Dallinger provides some helpers to facilitate realtime communication between
participants and the experiment using the WebSocket protocol.

The experiment server runs two WebSocket routes. The first, `/chat`, implements
a Publish-Subscribe pattern. Connecting to that service with a `channel`
argument in the url will subscribe a client to all messages sent to the named
channel. If the named "channel" doesn't already exist it will be created on the
server. Both clients (participants) and the experiment instance can subscribe
and create channels. The second, `/experiment-socket`, hands each incoming
message to the experiment on the web process holding the connection instead of
publishing it, and is described in its own section below.

The channel backend publishes all incoming messages to a redis queue. It also
looks for new messages on the queue and relays channel specific messages to all
channel subscribers (generally either participants or the experiment itself).

When a client makes a WebSocket connection to the `/chat?channel=<channel>`
route (see :doc:`The Web API <web_api>`) it opens a persistent connection to the
experiment over which it can send messages (to any channel except the reserved
`"dallinger_control"` channel) and will receive all messages published to the
`channel` named in the initial request.

Additionally, Experiment classes can provide a
:attr:`~dallinger.experiment.Experiment.channel` attribute which will
automatically subscribe the experiment class to the named channel. Experiments
that specify a channel will also be subscribed to a control channel named
`"dallinger_control"` to which client connection, disconnection, subscribe, and
unsubscribe messages are automatically sent. Such experiments should implement a
custom :func:`~dallinger.experiment.Experiment.receive_message` method to
receive and process incoming WebSocket messages.

Experiments may also send messages to all channel subscribers using the
:func:`~dallinger.experiment.Experiment.publish_to_subscribers` method.

It's possible for an experiment class to subscribe to messages on
additional WebSocket channels. To avoid duplicate subscriptions it's generally
best to create such subscriptions in your Experiment class's
:func:`~dallinger.experiment.Experiment.on_launch` method which is only run at
experiment launch time, or using the experiment's
:func:`~dallinger.experiment.Experiment.background_tasks`. For example::

    def on_launch(self):
        from dallinger.experiment_server.sockets import chat_backend
        chat_backend.subscribe(self, 'my_secondary_channel')


An experiment can create and subscribe to channels after launch, but would need
to be careful to ensure each channel is only ever subscribed once per experiment
run. This is likely to be difficult because the experiment potentially has many
instances running concurrently across multiple processes and servers.

Websocket messages are strings consisting of a channel name followed by a `:`
and then a message payload. The message payload is usually a string representing
a JSON object.

Messages are handled asynchronously by the
:func:`~dallinger.experiment.Experiment.receive_message` method of the
experiment class. Experiments which wish to override the default asynchronous
handling of WebSocket messages (e.g. because they retain non-persisted state in
the experiment instance that is needed to process the message) may override the
:func:`~dallinger.experiment.Experiment.send` method of the experiment class.

If your experiment implements synchronous handling of messages either using a
custom :func:`~dallinger.experiment.Experiment.send` or by sending the
`immediate` flag in your message payload, it will need to ensure that it takes
care to manage any database sessions. The
`dallinger.db.scoped_session_decorator` can be used to wrap functions and the
`dallinger.db.sessions_scope` contextmanager can provide more granular/repeated
session management.

The Experiment Socket
---------------------

Both of the paths described so far run the experiment's code on the process
that subscribed the experiment to the channel, which is the one that served
``/launch``.
Messages reach it through redis, and by default a worker handles them some time
later.

A connection to the ``/experiment-socket`` route works differently. Each
incoming message goes straight to the
:func:`~dallinger.experiment.Experiment.handle_websocket_message` method, on the
web process that owns the socket, before the next message is read. Nothing is
published to redis on the way. Use it when a participant's action has to be
acted on immediately, such as a move in a turn-based game::

    socket = new ReconnectingWebSocket(
      ws_scheme + location.host + "/experiment-socket" +
        "?channel=" + channel_id +
        "&participant_id=" + dallinger.identity.participantId +
        "&worker_id=" + dallinger.identity.workerId +
        "&scope=" + encodeURIComponent(page_scope)
    );

An experiment socket subscribes to ``channel`` just as a ``/chat`` connection
does, so broadcasts to that channel reach the browser the same way. Only the
inbound direction differs.

``channel`` is optional. A connection that leaves it out subscribes to nothing
and receives nothing, which suits a game socket that only reports moves. It can
still send, because each message carries its own channel prefix, which is
passed to the method as ``channel_name``.

``scope`` is optional, and Dallinger does not interpret it. Whatever the browser
sends is stored on the connection and reported back unchanged, both to the
method and in the ``client`` payload of every control channel event. It exists
because two connections from the same participant are otherwise
indistinguishable. What it should contain is the experiment's decision;
identifying the page the participant is on is one choice, and lets a handler
ignore a message from a page they have since left.

Messages must be text. Dallinger splits each one on its channel prefix, and a
binary frame has no prefix to split on, so the connection is closed with code
``1003`` and the reason ``text frames only``.

An experiment socket must name a participant that exists, because every message
is reported to the method as coming from someone. Dallinger closes the socket
otherwise, with code ``1008`` and the reason ``unknown participant``.
Two failures that are not the client's fault close with ``1013`` instead, which
tells the client to try again later: a participant lookup that raises, and an
experiment class that fails to build.

The lookup proves only that a row with that id exists. ``/experiment-socket`` is
not authenticated, so the id says which participant the connection claims to be,
not who is sending the messages. Treat it as Dallinger treats every other
``participant_id``.

``ReconnectingWebSocket`` reconnects after every close, and reports the close
code on its ``connecting`` event rather than on ``close``. A refusal is
therefore indistinguishable from a dropped network connection, and repeats
forever. Pass the socket to ``dallinger.stopReconnectingIfRefused`` to handle
it::

    socket = new ReconnectingWebSocket(...);
    dallinger.stopReconnectingIfRefused(socket, function (code, reason) {
      console.error("The server refused the connection: " + reason);
    });

The callback is optional. The socket is left in the ``CLOSED`` state, so code
that reads ``readyState`` can tell a refusal from a reconnect still in
progress. A close with any other code, including the ``1013`` above, still
reconnects.

Reaching Other Participants from a Handler
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A message that goes to the handler never reaches the channel, so no other client
sees it. That is what a turn-based game wants, since a player's raw move should
not be echoed to the room before the experiment has ruled on it. A chat room
wants the opposite.

Messages can be sent to particular participants using the
:func:`~dallinger.experiment.Experiment.publish_to_participants` method, which
is described in its own section below. To fan a message out to all of the
subscribers of a channel, publish it from the handler::

    def handle_websocket_message(
        self, message, *, channel_name, participant_id, scope, receive_time
    ):
        # ... act on the message, commit whatever it changed ...
        self.publish_to_subscribers(message, "chatroom_broadcast")

Publish to a channel the experiment does not subscribe to, as above, and give
the browsers that channel to listen on. Dallinger subscribes the experiment to
its :attr:`~dallinger.experiment.Experiment.channel` at launch, so publishing a
handled message back to that channel delivers it to the experiment a second
time, through :func:`~dallinger.experiment.Experiment.send` and a worker.

Leaving the publish out is easy to miss. The database rows are correct and the
sender's own browser shows the message, while every other client sees nothing.

Sessions and the Experiment Socket
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Dallinger removes the database session after each message, so a handler always
starts with an empty identity map, and nothing holds a transaction open between
messages. Two consequences for experiment code:

- Load rows inside the handler and let them go when it returns. An ORM object
  kept on the experiment instance, or on anything else that outlives the call,
  is detached by the time the next message arrives.
- Commit your own writes. Dallinger does not commit for you here, just as it
  does not for a worker event.

The experiment instance is built once per web process and shared by every sync
socket that process is serving, which is the arrangement the launched experiment
already has on the process that served ``/launch``. Keep per-participant state
off it.

The same rule reaches back into
:func:`~dallinger.experiment.Experiment.configure`. Dallinger removes the
session as soon as the constructor returns, so a row loaded there and kept on
``self`` is detached before the first message arrives, and stays that way for
the life of the process. Setting plain values from the configuration, which is
what ``configure`` is for, is unaffected.

An exception raised by a handler is logged, and the connection stays open.

What a Handler Blocks
~~~~~~~~~~~~~~~~~~~~~

A handler blocks the whole web process, not just the connection it came from.

Dallinger's web workers run under gunicorn's gevent worker, and gevent switches
greenlets only at a yield point. Nothing in ``psycopg2`` yields; it waits for
the database inside a C socket call. So while one handler waits on a query,
every other websocket on that worker, and every HTTP request it is serving,
waits with it.

Budget accordingly. A couple of indexed queries is fine. A sequential scan, an
external HTTP call, or anything whose duration grows with the number of
participants enrolled is not. Send that work to a worker with
``dallinger.db.get_queue()``, which is what the default
:func:`~dallinger.experiment.Experiment.handle_websocket_message` does. An
experiment that opens an experiment socket without overriding the method gets
the same asynchronous handling ``/chat`` gives.

A handler will typically dispatch on the message type, doing the work that has
to happen immediately and queueing the rest::

    def handle_websocket_message(
        self, message, *, channel_name, participant_id, scope, receive_time
    ):
        data = json.loads(message)
        if data["type"] == "move":
            participant = Participant.query.get(int(participant_id))
            # Assign a new dict rather than mutating the existing one
            participant.details = dict(
                participant.details,
                move=data["action"],
                at=receive_time.isoformat(),
            )
            db.session.commit()
            self.publish_to_participants(
                {"type": "move_accepted", "by": participant_id},
                participant_ids=[self.partner_of(participant_id)],
            )
        else:
            db.get_queue("high").enqueue(score_the_round, participant_id)

The explicit commit is required, because Dallinger removes the session once the
handler returns and discards any uncommitted work along with it.
``score_the_round`` must be a module-level function in the experiment package,
since the worker process imports it by name.

``details`` is an ordinary JSONB column with no change tracking, so SQLAlchemy
will only notice the write if the attribute is assigned a new value, and a
``datetime`` such as ``receive_time`` has to be converted with ``isoformat()``
before it can be stored in one.

A payload carrying the ``immediate`` flag is the exception. The default
implementation passes the message to
:func:`~dallinger.experiment.Experiment.send`, which runs
:func:`~dallinger.experiment.Experiment.receive_message` inline for such a
payload. On an experiment socket that inline work happens on the web process
rather than on a worker, and the budget above applies to it.

Making Database Waits Cooperative
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two changes would remove that budget, and Dallinger makes neither today.
``psycogreen.gevent.patch_psycopg()`` is only a few lines, but it puts
connections into psycopg2's asynchronous mode, which does not support ``COPY``,
and Dallinger uses ``COPY`` to export data. Psycopg 3 waits cooperatively on its
own and keeps ``COPY``, but it needs the SQLAlchemy 2.0 upgrade first, and
Dallinger pins ``sqlalchemy==1.4.54``. `Issue #9807
<https://github.com/Dallinger/Dallinger/issues/9807>`_ has the full comparison.


Sending to Specific Participants
--------------------------------

While :func:`~dallinger.experiment.Experiment.publish_to_subscribers` sends a
message to every subscriber of a channel, the
:func:`~dallinger.experiment.Experiment.publish_to_participants` method sends a
payload to particular participants, named by their participant ids::

    self.publish_to_participants(
        {"type": "move_accepted", "by": participant_id},
        participant_ids=[partner_id],
    )

The recipients do not need a channel of their own, and do not need to subscribe
to anything. Any connection which included a ``participant_id`` argument in its
url, on either the ``/chat`` or the ``/experiment-socket`` route, can be
addressed in this way, and the payload will be delivered to every connection
that participant currently holds, whichever web process is holding it. The
method may be called from anywhere, including a WebSocket handler, a worker
event, or an ordinary route.

This replaces the pattern of giving each participant a channel named after
them, such as ``participant_12_channel``. Named channels remain the natural
choice for a group of participants who should all receive the same messages.

A directed message is no more confidential than the channel name it replaces.
Neither WebSocket route is authenticated. ``/experiment-socket`` checks that
the participant exists and ``/chat`` checks nothing, so a connection is
addressed by the ``participant_id`` it claims rather than by one it has proved
it owns, and anyone who can guess a participant id can open a socket naming it
and be sent that participant's directed messages. Guessing
``participant_12_channel`` took the same knowledge. Treat the id as Dallinger
treats every other ``participant_id``, and keep out of a payload anything
another participant must not read.

Naming a participant who has no open connection, or who is not connected to this
deployment at all, delivers nothing and is not an error. As with a broadcast, no
message is buffered or replayed, so a payload published while a participant is
reconnecting will not reach them. Anything a client must not miss should be
stored in the database, with the directed message serving as a prompt to fetch
it.

A redis failure is the one delivery problem which is reported. It raises, and
the payload will have reached none of the recipients, so the call can be
retried as a whole.

Directed Message Format
~~~~~~~~~~~~~~~~~~~~~~~

Directed messages arrive on the client prefixed with the reserved
``dallinger_direct`` channel name, using the same ``channel:payload`` format as
every other WebSocket message, so a single connection can receive both channel
broadcasts and directed messages::

    socket.onmessage = function (msg) {
        // Ignore messages which are not directed to this participant
        if (msg.data.indexOf('dallinger_direct:') !== 0) { return; }
        // Parse the payload
        var data = JSON.parse(msg.data.substring('dallinger_direct:'.length));
        // Take different actions based on message type
        switch (data.type) {
           ...
        }
    };

Like ``dallinger_control``, the ``dallinger_direct`` channel is reserved for
Dallinger's own use. Experiments should not publish to it, and clients may
neither publish to it nor subscribe to it; the server discards such a message or
subscription and logs a warning. Both channels carry messages in the same format
as the ones a client expects to receive, so a subscriber would be given other
participants' messages as though they were its own.

Connection Scope
~~~~~~~~~~~~~~~~

A participant may hold more than one connection at a time, for example a page
which opens two sockets, or a reload whose previous socket has not yet timed
out. By default every one of them receives the payload. The optional ``scope``
argument limits delivery to those connections which included the same ``scope``
value in their url::

    def handle_websocket_message(
        self, message, *, channel_name, participant_id, scope, receive_time
    ):
        ...
        self.publish_to_participants(
            {"type": "accepted"}, participant_ids=[participant_id], scope=scope
        )

The handler is given the ``scope`` of the connection its message arrived on, so
replying with that value reaches the page which sent the message and leaves a
tab open on an earlier page untouched.

That value should not be passed on when addressing a different participant.
Their connections will have supplied a scope of their own, and a payload scoped
to the sender's page will silently reach none of them. Supply a scope when
addressing the same participant, and omit it otherwise, unless the experiment
has defined scope as a value which both participants share.

Dallinger compares the two values as strings and does not interpret them; what a
scope means is up to the experiment. A connection which supplied no scope will
only receive messages which were published without one.

Cross-Process Delivery
~~~~~~~~~~~~~~~~~~~~~~

The process which publishes a directed message delivers it to any matching
connections it holds itself, and publishes an envelope naming the recipients to
redis so that the other web processes can deliver it to theirs. Every process
reads every envelope and delivers to whichever of the named participants it
holds connections for. The payload is serialized once, by the publishing
process, so every recipient of a single call is sent identical bytes.


Client Implementation
---------------------

The default experiment layout includes a `basic websocket communication library
<https://www.npmjs.com/package/reconnecting-websocket>`_ which implements a
`ReconnectingWebSocket` object that can be used to establish channel
subscriptions, send messages to various channels, and receive messages on
subscribed channels.

Typically experiments set up a WebSocket connection after completing the initial
call to `createAgent` using code similar to this::

    var broadcast_socket;
    var open_socket = function (channel_id) {
        var ws_scheme = (window.location.protocol === "https:") ? 'wss://' : 'ws://';
        // Setup a websocket connection to the channel, passing our worker_id and participant_id
        socket = new ReconnectingWebSocket(
            ws_scheme + location.host + "/chat?channel=" + channel_id +"&worker_id=" + dallinger.identity.workerId + '&participant_id=' + dallinger.identity.participantId
        );
        // Once the connection is established, send an initial message to the channel
        socket.onopen(function () {
            socket.send(channel_id + ':{"message": "Hello world!"}');
        });
        // Handle any incoming messages
        socket.onmessage = function (msg) {
            // Ignore messages not from the channel subscribed channel
            if (msg.data.indexOf(channel_id + ':') !== 0) { return; }
            // Parse the payload
            var data = JSON.parse(msg.data.substring(channel_id.length + 1));
            // Example message data
            var type = data.type;
            // Take different actions based on message type
            switch(type) {
               ...
            }
        };
        return socket;
    };
    // Create the agent.
    var create_agent = function() {
        dallinger.createAgent()
            .done(function (resp) {
                ...
                broadcast_socket = open_socket("broadcast_channel");
            })
            .fail(function (rejection) {
                ...
            });
    };


When establishing a channel subscription using the `/chat` route, the client may
include `worker_id` and `participant_id` values. Those values will be included
in the automatically generated JSON messages alerting the experiment to
WebSocket connection, disconnection, subscription, and un-subscription events
over the `"dallinger_control"` channel.

Messages sent over the socket connection can be prefixed with any channel name,
not just the channel to which the connection is subscribed. The exception is
`"dallinger_control"`, which is reserved for the server's own connection and
subscription events. The experiment treats anything arriving on that channel as
genuine, so the server discards a client message addressed to it and logs a
warning. Additional subscriptions can be established by opening new websocket
connections to the `/chat` route with different `channel` values.


Experiment Channel Setup
------------------------

Many experiment use cases will only need a "broadcast channel" to which all
clients subscribe. That subscription can be established when the experiment
starts (i.e. when `createAgent` returns). This "broadcast channel" would be
separate from the one set in the `Experiment.channel` attribute, which we will
call the "experiment control channel".

Clients will receive all messages sent to the "broadcast channel" by either the
experiment or other clients. The messages will generally contain JSON payloads
that indicate the messages' purpose. For example, messages may have a `type`
property to differentiate e.g. "state" messages sent by the experiment server
from "chat" messages sent by other clients. Additionally, such "chat" messages
might have `room` or `recipient` properties to allow clients to filter
out messages not intended for them.

Generally, clients will send messages about their actions to the "experiment
control channel". Those messages will be processed by the experiment and will
not be relayed to other clients, because clients are not generally
subscribed to the "experiment control channel".

The experiment sends messages to all clients over the "broadcast channel", but
generally does not subscribe to the "broadcast channel". If an experiment needs
to handle messages sent by clients over the "broadcast channel", then it's
generally simplest for clients to send such messages both to the "broadcast
channel" and to the "experiment control channel" (perhaps with an additional
`broadcast` flag). It is possible to subscribe the experiment to the "broadcast
channel", but that would also require the experiment to handle/ignore the
messages that the experiment itself sends over that channel.


Multiple Client Channels
------------------------

If it's important for an experiment to have participant and/or group specific
channels, e.g. to ensure messages are only ever seen by their targets, or to
reduce the total number of messages sent to or processed by clients, then
clients can subscribe to multiple channels.

For example, after launch an experiment could broadcast a `create_chatroom` type
message with a `chatroom` property set to e.g. `"room_1"` and an array of
`participant_ids`. Clients could then subscribe to the `"room_1"` channel using
the `/chat` route only if their `participant_id` matches one of the values in
`participant_ids`. That way only the clients with the matching
`participant_ids` would receive messages for `"room_1"`.

If these chat room messages need to be handled by the experiment code, then the
clients could also send these messages to the "experiment control channel", with
an additional `chatroom` property to specify the channel. Alternatively, if the
names of all chatrooms could be determined at experiment launch time, then
duplicate messages can be avoided by having the experiment subscribe to all
chatrooms in :func:`~dallinger.experiment.Experiment.on_launch` or using
:func:`~dallinger.experiment.Experiment.background_tasks`.

Similarly, if the experiment needs to send messages privately to specific
participants, then every client could use the `/chat` route to subscribe to a
unique channel like `"participant_${participant_id}_channel"`, to which the
experiment instance could send private messages using
`self.publish_to_subscribers(payload, channel_name=channel)` or
`redis_conn.publish(f"participant_${participant_id}_channel", payload)`.
