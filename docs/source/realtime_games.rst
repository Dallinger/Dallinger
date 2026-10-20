Real-Time Games
===============

Dallinger's real-time engine plays games in which participants act at the same
time and see each other's actions within a fraction of a second, such as
movement games, games with turn timers, and bargaining. Dallinger runs each
game for the experiment: it applies the messages players' pages send as they
arrive, keeps the game's time, and sends each player's page a view of the
game, which is what that player may see of it.

An experiment with a real-time game:

1. defines a game type, a Python class holding the game's rules
2. lists the game type in its ``realtime_games``
3. starts a session of the game type for each group of players, and reads the
   session's outcome once it's over

Dallinger saves a record of every session, which is exported with the rest of
the experiment's data. Real-time games need redis 7.0 or later. A WebSocket
uses the real-time engine only if it joins a session when it connects, and
the experiment's other WebSockets work as
:doc:`Using WebSockets in Dallinger Experiments <using_websockets>` describes.

Writing a Game Type
-------------------

A game type is a subclass of :class:`~dallinger.realtime.RealtimeGame`.
The game below gives each player 30 seconds to make a sealed bid, and the
highest bid wins::

    from dallinger.realtime import RealtimeGame, Reject


    class SealedBid(RealtimeGame):
        channel = "sealed_bid"

        def initial_state(self, players):
            # Session time starts at 0, so bidding closes 30 seconds in
            return {
                "players": players,
                "bids": {},
                "deadline": 30,
                "closed": False,
            }

        def apply(self, state, player_id, message, now, sent):
            # The message comes from the player's browser and could hold
            # anything, so check it all before changing the state
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
            # Other players' bids stay hidden, and only the highest is shown
            # once the game is over
            bids = state["bids"]
            over = self.is_over(state)
            return {
                "my_bid": bids.get(player_id),
                "bids_made": len(bids),
                "highest_bid": max(bids.values(), default=None) if over else None,
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
  ``SealedBid`` does. It is also passed ``now``, the session time the message
  arrived, and ``sent``, a :class:`~dallinger.realtime.Sent` with what the
  page said about the message, such as when the browser sent it. Most games
  don't need ``sent``.
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
reserved channels, ``dallinger_control``, ``dallinger_direct``,
``dallinger_realtime_session`` and ``dallinger_time``, or the experiment's own
:attr:`~dallinger.experiment.Experiment.channel`. ``dallinger verify`` and
every deploy check the game types. If one is invalid, the experiment's web
processes and ``dallinger develop``'s server won't start, and a worker logs
the error and plays no sessions.

Messages a page sends on a game type's channel go only to the page's session,
or are dropped if the page hasn't joined one. They are never broadcast to the
channel's subscribers or passed to
:meth:`~dallinger.experiment.Experiment.handle_websocket_message`, which is
what keeps a game's hidden information hidden.

State and Time
~~~~~~~~~~~~~~

A game type's instance is shared by every session of that game type, so
everything about a session goes in its state, never on ``self``. Settings that
are the same for every session can go on ``self``, and a game type can read
them from the experiment's configuration in ``__init__``, so they can be
tuned without changing code. The experiment registers the setting and gives it
a default, as :doc:`Extra Configuration <extra_configuration>` describes, and
``config.txt`` can change it::

    from dallinger.config import get_config


    class SealedBid(RealtimeGame):
        channel = "sealed_bid"

        def __init__(self):
            self.bidding_seconds = get_config().get("bidding_seconds")

        def initial_state(self, players):
            return {
                "players": players,
                "bids": {},
                "deadline": self.bidding_seconds,
                "closed": False,
            }

        ...


    class Auction(Experiment):
        realtime_games = [SealedBid]

        @classmethod
        def extra_parameters(cls):
            get_config().register("bidding_seconds", int)

        @classmethod
        def config_defaults(cls):
            return {"bidding_seconds": 30}

The state, messages, views and outcome are plain JSON values: dicts, lists,
strings, numbers, ``True``, ``False`` and ``None``. Dallinger saves the state
as JSON after each change and loads it again, so a dict key comes back as a
string and a tuple as a list. A state built that way from the start behaves
the same before and after a save. Players are identified by their participant
ids as strings, so the ids work as keys in the state's dicts.

The methods are passed ``now``, the session time, in seconds. It starts at 0
and stops while the session isn't being played, for example during a
redeploy, so a pause doesn't use up a turn timer. Deadlines should be kept in
the state as session times.

A game can use Python's ``random`` module, for example to shuffle a deck or roll
a die. It can draw in the methods that change the state, ``apply``, ``tick``,
``on_join`` and ``on_leave``, and use what it drew in the state. ``view`` and
the other methods should only read what's there: Dallinger can call them several
times for the same state, so a number drawn in ``view`` could come out
differently each time.

A game whose sessions should replay exactly, for example to test it, keeps a
seed in its state and makes each draw from the seed and a count of the draws so
far::

    import random


    class DiceGame(RealtimeGame):
        ...

        def initial_state(self, players):
            return {"players": players, "seed": random.randrange(10**9), "draws": 0}

        def roll(self, state):
            # The same seed and count always give the same roll
            rng = random.Random(f"{state['seed']}:{state['draws']}")
            state["draws"] += 1
            return rng.randint(1, 6)

``roll`` is the game type's own method, which Dallinger never calls. The game
calls it from ``apply`` or ``tick``, wherever it needs a roll.

No method may use the database, and should return quickly. Work that needs the
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
second on average, 120 by default, and up to
:attr:`~dallinger.realtime.RealtimeGame.message_burst` at once, also 120 by
default. Dallinger drops the messages over the limit and logs a warning. The
burst allows for messages that queue up while the web process is busy and
then reach it all at once.

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

Game code that needs the database, for example to create an ``Info``, queues
an effect with :meth:`~dallinger.realtime.RealtimeGame.queue_effect`. The game
type's :meth:`~dallinger.realtime.RealtimeGame.handle_effect` then does the
work a few seconds later, on one of the experiment's worker processes::

    from dallinger import db
    from dallinger.models import Info, Participant


    class CoinGame(RealtimeGame):
        ...

        def apply(self, state, player_id, message, now, sent):
            ...
            # Player ids are strings, and participant ids are integers
            self.queue_effect("coin", {"participant_id": int(player_id)})

        def handle_effect(self, name, payload, session_row):
            if name == "coin":
                participant = Participant.query.get(payload["participant_id"])
                db.session.add(Info(origin=participant.nodes()[0], contents="coin"))

A player's pay is best worked out from the session's outcome, once it's over,
as described under Reading the Outcome, rather than in an effect. A
participant's ``bonus`` records the bonus Dallinger has paid them, and
Dallinger pays no bonus to a participant whose ``bonus`` is already set.

Only ``apply``, ``tick``, ``on_join`` and ``on_leave`` can queue effects. An
effect queued by an ``apply`` that then raises ``Reject`` is dropped.

Each effect is handled once, in the order it was queued. Dallinger saves the
changes ``handle_effect`` makes together with the session's record, so
``handle_effect`` doesn't call ``db.session.commit()`` itself. Code that
should run only once the changes are saved, such as sending a message to a
page, can be passed to :func:`~dallinger.db.run_after_commit`.

Sessions
--------

A session is one play of a game type by one group of players, such as a single
auction. The game type holds the rules, and each session is one game played by
those rules, with its own players, its own state and its own session time,
which starts at 0. Each session has an id, an integer, and any number of
sessions, of one game type or several, can run at once.

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
                # find it. Changes made inside network.details aren't saved,
                # so this assigns it a new dict.
                network.details = dict(network.details, session_id=session_id)

``add_node_to_network`` runs when a player's page creates their node with
:js:func:`dallinger.createAgent`, so the session starts once the last player
of the group has done that. ``create_realtime_session`` returns the new
session's id, an integer. The session is already running by then, and keeps
running whether or not the caller commits. The experiment keeps the id, as
``Auction`` does in the network's details, because every later step needs it:
the players' pages use it to join, and the experiment passes it to the other
session functions.

A player can also be a bot, whose messages come from the game type's ``bot``
method rather than from a page. A bot's participant id goes in the list of
players, and in ``bots`` as well. Dallinger doesn't let a bot's page join the
session, so a participant goes in ``bots`` only if nothing will open the
game's page for them. Dallinger's ``HighPerformanceBotBase`` bots sign up
without opening a browser, and their ``recruiter_id`` starts with
``"bots:"``::

    players = [n.participant for n in network.nodes()]
    bots = [p.id for p in players if p.recruiter_id.startswith("bots:")]
    session_id = create_realtime_session(
        SealedBid, [p.id for p in players], bots=bots
    )

A bot that drives a browser, such as one built on ``BotBase``, opens the
game's page as a person would, so it plays as an ordinary player and makes its
moves on the page.

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
- the session time reaches the game type's
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

- a game type's method raises an error or calls ``sys.exit()``, other than
  ``apply`` raising ``Reject``
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
carries its sessions on from their last save. Their session time stops in the
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

.. autodata:: dallinger.db.REALTIME_SESSION_CHANNEL

.. autodata:: dallinger.db.TIME_CHANNEL
