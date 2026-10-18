Real-Time Games
===============

Dallinger's real-time engine plays games in which participants act at the same
time and see each other's actions within a fraction of a second, such as
movement games, games with turn timers, and bargaining. An experiment defines a
game type, a Python class holding the game's rules, and starts a session of it
for each group of players. Dallinger plays every session: it applies each
player's messages to the session's state as they arrive, runs the game's timed
updates, and sends each player's page a view of the state.

Game code works only with plain JSON values. Dallinger keeps each session in
redis while it is played, and saves a record of it in Postgres, which is
exported with the rest of the experiment's data.

The real-time engine is opt-in. A WebSocket uses it only if it joins a session
when it connects, and every other WebSocket works as
:doc:`Using WebSockets in Dallinger Experiments <using_websockets>` describes.
The engine needs redis 7.0 or later.

Writing a Game Type
-------------------

A game type is a subclass of :class:`~dallinger.realtime.RealtimeGame`.
The game below gives each player 30 seconds to make a sealed bid, and the
highest bid wins::

    from dallinger.realtime import RealtimeGame, Reject


    class SealedBid(RealtimeGame):
        channel = "sealed_bid"

        def initial_state(self, players):
            # The session's clock starts at 0, so bidding closes 30 seconds in
            return {
                "players": players,
                "bids": {},
                "deadline": 30,
                "closed": False,
            }

        def apply(self, state, player_id, message, now, sent):
            # Check everything before changing the state
            if player_id in state["bids"]:
                raise Reject("already bid")
            bid = message.get("bid") if isinstance(message, dict) else None
            if type(bid) is not int or not 1 <= bid <= 100:
                raise Reject("a bid is a whole number from 1 to 100")
            state["bids"][player_id] = bid

        def next_deadline(self, state):
            # Ask for a tick when bidding closes
            return state["deadline"]

        def tick(self, state, now):
            if now >= state["deadline"]:
                state["closed"] = True

        def is_over(self, state):
            all_bid = len(state["bids"]) == len(state["players"])
            return state["closed"] or all_bid

        def view(self, state, player_id):
            # Other players' bids stay hidden until the game is over
            return {
                "my_bid": state["bids"].get(player_id),
                "bids_made": len(state["bids"]),
                "bids": state["bids"] if self.is_over(state) else None,
            }

        def outcome(self, state, reason):
            bids = state["bids"]
            winner = max(bids, key=bids.get) if bids else None
            return {"winner": winner, "bids": bids}

The :attr:`~dallinger.realtime.RealtimeGame.channel` is the WebSocket
channel the game's pages send their messages on. Dallinger calls the other
methods as the game goes on:

- :meth:`~dallinger.realtime.RealtimeGame.initial_state` is called once,
  when the session starts, with the players' participant ids, and returns the
  state the game starts from.
- :meth:`~dallinger.realtime.RealtimeGame.apply` is called with each
  message a player's page sends, as soon as it arrives. It changes the state in
  place, or refuses the message by raising
  :class:`~dallinger.realtime.Reject` with a reason. Changes made before
  ``Reject`` is raised are kept, so ``apply`` should check everything first, as
  ``SealedBid`` does.
- :meth:`~dallinger.realtime.RealtimeGame.tick` is the game's timed
  update, for anything that happens because time has passed, such as a turn
  timer running out. :attr:`~dallinger.realtime.RealtimeGame.tick_rate`
  says how many times a second it runs. ``SealedBid`` leaves it at the default
  of 0, so ``tick`` runs only when the game asks for it.
- :meth:`~dallinger.realtime.RealtimeGame.next_deadline` is how the game
  asks. It returns the session time at which ``tick`` should next run, or
  ``None`` if there's nothing to wait for. ``SealedBid`` returns its deadline,
  so ``tick`` runs once, 30 seconds in, and closes the bidding. A deadline
  that ``tick`` has already run for doesn't run it again, so
  ``next_deadline`` can keep returning it.
- :meth:`~dallinger.realtime.RealtimeGame.is_over` is checked after every
  change to the state, and the session ends when it returns true: here, once
  bidding has closed or every player has bid.
- :meth:`~dallinger.realtime.RealtimeGame.view` returns what one player
  may see of the state. In a game without ticks, like this one, Dallinger
  sends each player a new view whenever the state changes. The view goes to
  the player's browser, where they can read all of it, so it should leave out
  anything they shouldn't know, as ``SealedBid`` does with the other players'
  bids. A game with nothing to hide can return the state itself.
- :meth:`~dallinger.realtime.RealtimeGame.outcome` is called once, when
  the session ends, and returns the session's result, which is saved in
  Postgres for the experiment to read.

Game Types in an Experiment
~~~~~~~~~~~~~~~~~~~~~~~~~~~

An experiment lists its game types in its
:attr:`~dallinger.experiment.Experiment.realtime_games` attribute::

    class Auction(Experiment):
        realtime_games = [SealedBid]

Each game type needs a channel of its own, which can't be one of Dallinger's
reserved channels, ``dallinger_control``, ``dallinger_direct`` and
``dallinger_time``, or the experiment's own
:attr:`~dallinger.experiment.Experiment.channel`. The experiment's web
processes check the game types when they start, and won't start if one is
invalid.

Frames a page sends on a game type's channel go only to the page's session,
or are dropped if the page hasn't joined one. They are never broadcast to the
channel's subscribers or passed to
:meth:`~dallinger.experiment.Experiment.handle_websocket_message`, which is
what keeps a game's hidden information hidden.

State and Time
~~~~~~~~~~~~~~

A game type's instance is shared by every session of that game type, so
everything about a session goes in its state, never on ``self``. A subclass can
read its settings from the experiment's configuration in ``__init__``, so they
can be tuned without changing code.

The state, messages, views and outcome are plain JSON values. Dallinger saves
the state as JSON after each change and loads it again, so a dict key comes
back as a string and a tuple as a list. A state built that way from the start
behaves the same before and after a save. Players are identified by their
participant ids as strings, so the ids work as keys in the state's dicts.

The methods are passed ``now``, the session's own clock, in seconds. It starts
at 0 and stops while the session isn't being played, for example during a
redeploy, so a pause doesn't use up a turn timer. Deadlines should be kept in
the state as times on that clock. A game that needs random numbers should keep
its random generator's state in the state too, since anything kept elsewhere is
lost when the session is saved and loaded again.

No method may use the database, and none should take long. Work that needs the
database should be queued as an effect, which is described in its own section
below.

Moving Games and Ticks
~~~~~~~~~~~~~~~~~~~~~~

A game in which things move, rather than wait, sets a ``tick_rate``, such as
20 or 30, and moves things along in ``tick``. In a game with ticks, every tick
sends every player a view, even if nothing changed, so pages get views at a
steady rate. The player who sent a message is also sent a view as soon as it
has been applied, so they see the result of their own move straight away, and
the other players see it with the next tick. Setting
:attr:`~dallinger.realtime.RealtimeGame.send_views_on_messages` to
``False`` turns those extra views off, which suits a page that already shows
its own moves and sends many messages.

Messages don't wait for a tick. ``apply`` and ``tick`` are called in the order
things happened, so a message received just before a tick is applied before
it.

Each page may send up to
:attr:`~dallinger.realtime.RealtimeGame.max_messages_per_second` messages a
second on average, 120 by default, with short bursts allowed. Dallinger drops
the messages over the limit and logs a warning.

Joins, Leaves and Bots
~~~~~~~~~~~~~~~~~~~~~~

:meth:`~dallinger.realtime.RealtimeGame.on_join` is called when a player
opens the game's page, and
:meth:`~dallinger.realtime.RealtimeGame.on_leave` when they close it. A
player who reloads the page leaves and joins again. By default the game
carries on without a player who has left, and a game type can override
``on_leave`` to pause or end the game.

A bot is a player Dallinger plays for. Its moves come from the game type's
:meth:`~dallinger.realtime.RealtimeGame.bot` method, which is given the
bot's view and returns its next message. Bots' messages go through ``apply``
like any other player's, so the rest of the game code doesn't need to treat
them differently.

Effects
~~~~~~~

Game code that needs the database, for example to create an ``Info`` or add to
a participant's bonus, queues an effect with
:meth:`~dallinger.realtime.RealtimeGame.queue_effect`. The game type's
:meth:`~dallinger.realtime.RealtimeGame.handle_effect` then does the work
a few seconds later, on one of the experiment's worker processes::

    from dallinger.models import Participant


    class CoinGame(RealtimeGame):
        ...

        def apply(self, state, player_id, message, now, sent):
            ...
            self.queue_effect("coin", {"participant_id": int(player_id)})

        def handle_effect(self, name, payload, session_row):
            if name == "coin":
                participant = Participant.query.get(payload["participant_id"])
                participant.bonus = (participant.bonus or 0) + 0.01

Only ``apply``, ``tick``, ``on_join`` and ``on_leave`` can queue effects. An
effect queued by an ``apply`` that then raises ``Reject`` is dropped.

Each effect is handled once, in the order it was queued. ``handle_effect``
must not commit, since Dallinger commits once the effect is saved in the
session's record. Code that should run only after that commit, such as sending
a message to a page, can be passed to :func:`~dallinger.db.run_after_commit`.

Sessions
--------

The experiment's own code does three things with a session: it starts the
session, passes the session's id to the players' pages, and reads the outcome
once the session is over. Everything in between happens automatically:
Dallinger plays the game, ends it when it's over and saves its record.

Starting a Session
~~~~~~~~~~~~~~~~~~

The experiment's code starts a session by calling
:func:`~dallinger.realtime.create_realtime_session` with the game type
and the participant ids of the players. The place to call it is wherever the
experiment knows a group is complete. In an experiment that puts each group in
a network, that's when the network fills::

    from dallinger.experiment import Experiment
    from dallinger.realtime import create_realtime_session


    class Auction(Experiment):
        realtime_games = [SealedBid]

        def add_node_to_network(self, node, network):
            network.add_node(node)
            if network.full:
                players = [n.participant_id for n in network.nodes()]
                session_id = create_realtime_session(SealedBid, players)
                # Keep the id where the players' pages, and the bonus, can
                # find it
                network.details = dict(network.details, session_id=session_id)

``create_realtime_session`` returns the new session's id, an integer. The
session is already running by then, and keeps running whether or not the
caller commits. The experiment keeps the id, as ``Auction`` does in the
network's details, because every later step needs it: the players' pages use
it to join, and the experiment passes it to the other session functions.

Any number of sessions, of one game type or several, can run at once. A player
can also be a bot, played automatically with the game type's ``bot`` method:
its participant id goes in ``bots`` as well as in the list of players.

Each player's page joins the session by opening a WebSocket, on either
``/experiment-socket`` or ``/chat``, with the session's id as its ``session``
argument. Dallinger automatically checks that the participant is one of the
session's players, and refuses the connection if not. It doesn't check who is
on the other end of a socket, so an experiment that needs to can check
``/experiment-socket`` connections itself with
:meth:`~dallinger.experiment.Experiment.accept_websocket_connection`. The
frames a page sends and receives are listed in the socket protocol reference
below.

While a Session Is Played
~~~~~~~~~~~~~~~~~~~~~~~~~

Dallinger plays the session automatically from the moment it starts. It
calls the game type's methods as messages arrive and as time
passes, and sends each player their views, so the experiment's code calls
nothing while the game is played. An experiment that wants to show a session's
progress, for example on a route of its own, can pass the session's id to
:func:`~dallinger.realtime.realtime_state`, which returns the session's
state, a moment behind the game.

Endings
~~~~~~~

Dallinger ends a session automatically when any of these happens:

- ``is_over`` returns true
- the session's clock reaches the game type's
  :attr:`~dallinger.realtime.RealtimeGame.max_duration`
- no player other than a bot has opened the game's page within
  :attr:`~dallinger.realtime.RealtimeGame.join_timeout`, which is 60
  seconds by default

The experiment's code can also end a session early, for example when a player
drops out, by calling :func:`~dallinger.realtime.end_realtime_session`
with the session's id and a reason of its own.

However a session ends, Dallinger then automatically calls ``outcome`` with the
reason, such as :data:`~dallinger.realtime.game.FINISHED`, so a game can score
one that was cut short. It sends each player a final view, saves the ending to
Postgres a moment later, and then tells each player's page that the ending is
saved, so the page can wait for that before it's submitted.

Reading the Outcome
~~~~~~~~~~~~~~~~~~~

The experiment's code reads a session's outcome by passing the session's id to
:func:`~dallinger.realtime.realtime_result`, for example in
:meth:`~dallinger.experiment.Experiment.bonus`, which Dallinger calls when a
participant's assignment is submitted::

    from dallinger.realtime import realtime_result


    class Auction(Experiment):
        ...

        def bonus(self, participant):
            network = participant.nodes()[0].network
            outcome = realtime_result(network.details["session_id"])
            if outcome and outcome["winner"] == str(participant.id):
                return 1.0
            return 0

``realtime_result`` returns what ``outcome`` returned once the ending is saved,
and ``None`` until then. A player's result should be taken from that saved
outcome rather than from anything the browser sends.

Failures
~~~~~~~~

Dallinger fails a session when its game code goes wrong:

- a game type's method raises an error, other than ``apply`` raising
  ``Reject``
- a method returns a value that isn't JSON
- the methods run for longer than the game type's
  :attr:`~dallinger.realtime.RealtimeGame.time_limit`
- ``handle_effect`` raises an error

A failed session ends with the reason :data:`~dallinger.realtime.game.FAILED`,
so its players can still move on, and the experiment's other sessions carry
on. ``outcome`` is given the state from before the error. The session's
:class:`~dallinger.models.RealtimeSession` row has the status ``failed`` and
the error's traceback, and the experiment decides what its players are paid.

The Record in Postgres
----------------------

Each session's record is kept in two tables, which are exported with the rest
of the experiment's data. :class:`~dallinger.models.RealtimeSession` has a row
per session, with its game type, its players, its status, its start and end
times, why it ended, its outcome and its final state.
:class:`~dallinger.models.RealtimeEvent` has a row per saved event, in the
order they happened:

- each message, with its sender, its payload, when it arrived, and whether it
  was accepted or rejected, with the reason
- each effect, with its name and payload
- copies of the state, about every
  :attr:`~dallinger.realtime.RealtimeGame.checkpoint_interval` seconds of
  session time, 5 by default
- the ending, with its reason, the outcome and the final state
- the clock measurements a page reports, so browser times can be put on the
  server's clock during analysis

:meth:`~dallinger.realtime.RealtimeGame.save_message` decides which
messages are saved, so a game can leave out messages it gets many of, such as
moves into a wall. Views aren't saved. The record is written a few seconds
behind the game, and an export includes every finished session in full.
``--scrub-pii`` rewrites only ``participant.csv``, so the payloads in
``realtime_event.csv`` stay in a scrubbed export.

Running Games
-------------

Sessions are played by runners, processes Dallinger starts for the experiment.
When an experiment has game types, each of its worker processes starts a
runner beside it, under ``dallinger debug`` and on every deployment, and starts
it again if it stops. Nothing needs configuring.

An experiment with more than one worker process, set with
``num_dynos_worker``, has a runner for each, and the runners share its
sessions between them. If a runner stops, another runner, or its replacement,
carries its sessions on from their last save. The sessions' clocks stop in the
meantime, so players see the game pause.

A runner plays all of its sessions in turn, so slow game code in one session
delays the others. As a rough guide, 50 sessions at 20 ticks a second means
1,000 calls to ``tick`` a second, each followed by a call to ``view`` for every
player, which is fine if each session's share takes well under a millisecond.
More worker processes add more runners.

Runners log at the experiment's ``loglevel_worker``. They log each session
that fails, with its error, and warn when they fall behind, naming the slowest
sessions, so slow game code shows up while testing.

API Reference
-------------

Game Type Reference
~~~~~~~~~~~~~~~~~~~

.. autoclass:: dallinger.realtime.RealtimeGame
    :members:
    :member-order: bysource

.. autoexception:: dallinger.realtime.Reject

.. autoclass:: dallinger.realtime.Sent

.. autofunction:: dallinger.realtime.validate_game_types

.. autodata:: dallinger.realtime.game.FINISHED

.. autodata:: dallinger.realtime.game.MAX_DURATION

.. autodata:: dallinger.realtime.game.NOT_JOINED

.. autodata:: dallinger.realtime.game.FAILED

.. autodata:: dallinger.realtime.game.MAX_TIME_LIMIT

.. autodata:: dallinger.realtime.runner.MAX_HANDOVERS

Session Reference
~~~~~~~~~~~~~~~~~

.. automodule:: dallinger.realtime.store

.. autofunction:: dallinger.realtime.create_realtime_session

.. autofunction:: dallinger.realtime.realtime_state

.. autofunction:: dallinger.realtime.end_realtime_session

.. autofunction:: dallinger.realtime.realtime_result

.. autodata:: dallinger.realtime.store.ENDED_SESSION_TTL

.. autofunction:: dallinger.db.run_after_commit

Record Reference
~~~~~~~~~~~~~~~~

.. autoclass:: dallinger.models.RealtimeSession
    :members:
    :member-order: bysource
    :exclude-members: metadata, registry

.. autoclass:: dallinger.models.RealtimeEvent
    :members:
    :member-order: bysource
    :exclude-members: metadata, registry

Socket Protocol Reference
~~~~~~~~~~~~~~~~~~~~~~~~~

.. automodule:: dallinger.realtime.session_sockets

.. automodule:: dallinger.realtime.delivery

.. autodata:: dallinger.db.TIME_CHANNEL
