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
2. lists the game type in its ``realtime_games`` property
3. starts a session of the game type for each group of players, and reads the
   session's outcome once it's over
4. has a game page, which shows each player their view and sends their messages

Dallinger saves a record of every session, which is exported with the rest of
the experiment's data. A WebSocket uses the real-time engine only if it joins
a session, or waits for one, when it connects, and the experiment's other
WebSockets work as
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
                "deadline": state["deadline"],
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
:attr:`~dallinger.experiment.Experiment.realtime_games` property::

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
player who reloads the page leaves and joins again. A bot has no page, so it
joins as the session starts, before its first move, and never leaves. By
default the game carries on without a player who has left, and a game type can
override ``on_leave`` to pause or end the game.

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

The experiment's own code does two things with a session: it starts the
session, and reads the outcome once the session is over. Everything in between
happens automatically: Dallinger tells the players' pages that the session has
started, plays the game, ends it when it's over and saves its record.

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
                create_realtime_session(SealedBid, players)

``add_node_to_network`` runs when a player's page creates their node with
:js:func:`dallinger.createAgent`, so the session starts once the last player
of the group has done that. ``create_realtime_session`` returns the new
session's id, an integer. Like any other change to the database, the session
starts once it's committed, so code that starts one outside Dallinger's routes
must call ``db.session.commit()`` afterwards. Dallinger tells the players'
pages that the session has started, and the experiment finds each player's
sessions from the participant, as described below, so ``Auction`` doesn't keep
the id. An experiment keeps it to use the other session functions, such as
ending the session early.

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

A bot that the game type plays for has nothing left to do once it has joined,
so its ``participate`` method returns and the bot signs off. The game is still
played to its end, since the experiment isn't complete while any of its
sessions is running. The bot has signed off before its games end, though, so
the experiment's :meth:`~dallinger.experiment.Experiment.bonus` and
:meth:`~dallinger.experiment.Experiment.data_check` run for it without their
outcomes::

    import requests

    from dallinger.bots import HighPerformanceBotBase


    class Bot(HighPerformanceBotBase):
        def participate(self):
            # Creating the bot's node puts it in a network, as createAgent
            # does for a page
            url = "{}/node/{}".format(self.host, self.participant_id)
            result = requests.post(url)
            if not result.ok:
                self.log("Couldn't join: {}".format(result.text))

A bot that plays the game itself, from outside the experiment's processes,
is an ordinary player and isn't listed in ``bots``. One that drives a browser,
such as one built on ``BotBase``, opens the game's page as a person would and
makes its moves on the page. One that talks to the experiment over HTTP and
WebSockets, such as one started with ``dallinger bot``, uses the web API and
the session's socket the way the game's page does, and finds out the game is
over from the session's ending, as the page does.

How each player's page joins the session is described in the section on game
pages below.

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

The experiment isn't complete while any of its sessions is running, even once
every participant has signed off. A participant who plays several sessions one
after another needs the next one created before the last one's ending is
saved, for example from the last one's ``handle_effect``, or the experiment
can be complete in between.

Reading the Outcome
~~~~~~~~~~~~~~~~~~~

The experiment's code finds a player's sessions by passing the participant
and the game type to :func:`~dallinger.realtime.realtime_sessions_for`, for
example in :meth:`~dallinger.experiment.Experiment.bonus`, which Dallinger
calls when a participant's assignment is submitted::

    from dallinger.realtime import realtime_sessions_for


    class Auction(Experiment):
        ...

        def bonus(self, participant):
            pay = 0
            for session in realtime_sessions_for(participant, SealedBid):
                if session.status == "ended":
                    # Player ids in the game are strings
                    if session.outcome["winner"] == str(participant.id):
                        pay += 1.0
            return pay

``realtime_sessions_for`` returns the participant's sessions of the game type,
oldest first, so the same code works for a participant who plays one auction
or several rounds of it. Each session is a
:class:`~dallinger.models.RealtimeSession`. Its ``status`` is ``running``
until the session's ending is saved, then ``ended``, or ``failed`` if
something went wrong, as described below. Its ``outcome`` is what the game
type's ``outcome`` method returned, once the ending is saved. A failed session
has no outcome, only ``None``, if Dallinger couldn't start it or save its
record, so code that reads a failed session's outcome should check for that. A
player's result should be taken from the saved outcome rather than from
anything the browser sends.

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

Game Pages
----------

A game's page is an experiment page that uses Dallinger's JavaScript helpers to
join its session, send the player's messages and draw the views it is sent.
The helpers for sessions are in ``dallinger-realtime.js``. The base layout
loads it after ``dallinger2.js`` when the experiment's ``realtime_games``
property lists any game types, so a page that extends the layout needs nothing
more. A page that replaces the layout's ``libs`` block, or doesn't use the
layout, loads the script itself, after ``dallinger2.js``:

.. code-block:: html+jinja

    <script src="{{ url_for('static', filename='scripts/dallinger-realtime.js') }}"></script>

Every helper is listed in the
:ref:`JavaScript API's real-time sessions section <realtime-sessions-label>`.

``Auction`` starts a session once a network is full, so each player's node has
to exist before the game can start. The page before the game's page, such as
the instructions or a waiting room, creates it with
:js:func:`dallinger.createAgent`, and the game's page only joins the session.
That keeps the game's page safe to reload: it finds a running session again,
whereas calling ``createAgent`` a second time would put the participant in
another network.

The page below plays ``SealedBid``. It shows how many bids have been made and
how long is left, takes the player's bid, says why a bid didn't count, and
shows the highest bid once bidding has closed:

.. code-block:: html+jinja

    {% extends "layout.html" %}

    {% block body %}
        <p>Bids made: <span id="bids-made">0</span></p>
        <p>Bidding closes in <span id="timer"></span> seconds.</p>
        <form id="bid-form">
            <input type="number" id="bid" min="1" max="100" />
            <button type="submit">Bid</button>
        </form>
        <p id="error"></p>
        <p id="result"></p>
    {% endblock %}

    {% block scripts %}
    <script>
      dallinger.joinRealtimeSession('sealed_bid').done(function (socket) {
        var deadline = null;

        // Draw the game from each new view
        socket.onView(function (view) {
          deadline = view.deadline;
          $('#bids-made').text(view.bids_made);
          if (view.my_bid !== null) {
            $('#bid-form').hide();
          }
        });

        // Send the bid to the game
        $('#bid-form').on('submit', function (event) {
          event.preventDefault();
          $('#error').text('');
          socket.send('sealed_bid', {bid: Number($('#bid').val())});
        });

        // Tell the player why a bid didn't count
        socket.onRejected(function (number, reason) {
          $('#error').text('That bid didn\'t count: ' + reason);
        });

        // Count down to the deadline in session time
        setInterval(function () {
          var now = socket.sessionTime();
          if (now !== null && deadline !== null) {
            $('#timer').text(Math.ceil(Math.max(0, deadline - now)));
          }
        }, 250);

        // Show the highest bid, then move on once the result is saved
        socket.onEnded(function (reason, view) {
          $('#bid-form').hide();
          if (view.highest_bid !== null) {
            $('#result').text('The highest bid was ' + view.highest_bid);
          } else if (view.bids_made === 0) {
            $('#result').text('No one bid.');
          } else {
            $('#result').text('The game was stopped before bidding closed.');
          }
        });
        socket.resultSaved().done(function () {
          dallinger.goToPage('questionnaire');
        });
      });
    </script>
    {% endblock %}

The sections below describe each part of the page.

Joining a Session
~~~~~~~~~~~~~~~~~

A game's page usually opens before its session exists, since the experiment
starts the session once a group is complete. The page joins it with
:js:func:`dallinger.joinRealtimeSession`, passing the game type's channel. The
returned promise resolves with the page's socket for the session once the
experiment has started a session of that game type with the participant as a
player. If the participant is already playing one, it resolves at once, so a
page that is reloaded during a game finds its session again. A session stops
counting once its ending is saved, a moment after it ends, so a page reloaded
after its game has ended keeps waiting.
The page sets the socket's callbacks, such as ``onView``, as soon as it has the
socket, as ``SealedBid``'s page does.

A participant who plays several sessions of the game type, one after another,
passes the id of the session the page already has, the socket's ``session``,
as the ``afterSession`` option, so that only a newer one counts.

Dallinger refuses a connection to a session from a participant who isn't one
of its players. It doesn't check who is on the other end of a connection, so
an experiment that needs to can check connections itself with
:meth:`~dallinger.experiment.Experiment.accept_websocket_connection`, which
also checks the connection ``joinRealtimeSession`` waits on.

A page that also uses a chat channel waits for its session with
:js:func:`dallinger.waitForRealtimeSession`, which resolves with the session's
id, and joins it by passing :js:func:`dallinger.openChatSocket` that id as its
``session`` option and the game type's channel as its ``gameChannel``. The
waiting connection is checked as above, but a ``/chat`` connection can join a
session without ``accept_websocket_connection``'s check.

Views and Messages
~~~~~~~~~~~~~~~~~~

The socket's :js:func:`~dallinger.Socket.onView` callback is called with each
new view of the game: when the page joins the session, again after a
reconnect, and whenever the game changes. It is only called with views newer
than the last one, so the page can always draw the view it's given. The
callback is also passed details about the view, such as the session time it
shows and whether a tick or a message made the change.

The page sends the player's messages with the socket's ``send`` method, on the
game type's channel. Each message goes to the game type's ``apply`` method,
and nowhere else. A message sent while the connection is down waits, and goes
out once the connection reopens. ``send`` returns the message's number, and if
``apply`` rejects the message, the socket's
:js:func:`~dallinger.Socket.onRejected` callback is called with that number
and the reason ``apply`` gave ``Reject``, as ``SealedBid``'s page does to tell
the player why a bid didn't count. A message rejected just before the
connection dropped isn't reported.

The End of the Session
~~~~~~~~~~~~~~~~~~~~~~

When the session ends, the socket's :js:func:`~dallinger.Socket.onEnded`
callback is called once, with the reason it ended and the player's final view,
so the page can stop taking moves and show how the game turned out. The final
view can reach ``onView`` after ``onEnded``, so the page shows the result from
the view ``onEnded`` is passed.

The page waits for :js:func:`~dallinger.Socket.resultSaved` before it is
submitted or moves on, so that the experiment can read the outcome, for
example in its ``bonus`` method. A failed session's result is saved too, so the
page can move on either way.

Time
~~~~

The socket's :js:func:`~dallinger.Socket.sessionTime` method gives the
session time now, the ``now`` the game type's methods would be passed at that
moment. ``SealedBid``'s page uses it to count down to the deadline in its
view. It keeps counting between views, and since session time stops while the
session is paused, the next view can move it back a little.

To estimate it, the socket measures the server's clock when it connects, and
then about every 30 seconds until the session ends. The measurements are saved
in the session's record, so that an analysis can put the browser times of the
players' messages on the server's clock. A page can do the same with
:js:func:`~dallinger.Socket.serverTime`, which converts a time on the browser's
clock, from :js:func:`dallinger.browserTime`, to the server's clock, so that
moments on different players' pages can be compared.

Prediction and Interpolation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Prediction and interpolation are optional, for pages that need smoother
movement than the views alone give. A page that draws only the views it is
sent shows each of the player's moves once the game has applied it and the
view has come back, a round trip after the player made it. In a game with a
``tick_rate``, the page also sees the other players jump from one tick view to
the next. Many games need nothing more, including ``SealedBid`` and many simple
games in which players move. When the views alone aren't smooth enough, as in
a fast game where several players move around at once, a page can show the
player's own moves at once with prediction, and the other players moving
smoothly with interpolation. Each works without the other. The page below
assumes a game type whose view holds the player's own position as ``me`` and
the other players' positions as ``others``, listed in the same order in every
view:

.. code-block:: javascript

    dallinger.joinRealtimeSession('moves', {
      // Do to the view what apply does to the state
      predict: function (view, message) {
        view.me.x += message.dx;
        view.me.y += message.dy;
      },
      // Place the other players between two tick views
      interpolate: function (a, b, fraction) {
        return {
          others: a.others.map(function (player, i) {
            var next = b.others[i];
            return {
              x: player.x + (next.x - player.x) * fraction,
              y: player.y + (next.y - player.y) * fraction
            };
          })
        };
      }
    }).done(function (socket) {
      function draw() {
        var predicted = socket.predictedView();
        var interpolated = socket.interpolatedView();
        if (predicted !== null) { drawPlayer(predicted.me); }
        if (interpolated !== null) { interpolated.others.forEach(drawPlayer); }
        requestAnimationFrame(draw);
      }
      requestAnimationFrame(draw);
    });

:js:func:`~dallinger.Socket.predictedView` is the newest view with
``predict`` applied to each of the player's messages that the game hasn't
handled yet. ``predict`` has to do to the view what ``apply`` does to the
state, or the player's piece jumps when the next view arrives. So each
movement message should say how far, or for how long, the player moved, rather
than ``tick`` moving players while a key is held, which the page can't
predict. A move the game rejects is undone by the next view.

:js:func:`~dallinger.Socket.interpolatedView` shows the game two tick
intervals behind ``sessionTime``, between the tick views either side of that
time. ``interpolate`` is passed those two views and how far between them that
time falls, from 0 to 1, and returns a new view in between. The
``interpolationDelay`` option sets how many tick intervals behind it draws. A
longer delay copes better with tick views that arrive late, but shows the game
further in the past. The example's ``interpolate`` pairs the other players by
their place in ``others``, so a game in which players join or leave mid-game
lists them by participant id instead, and ``interpolate`` pairs them by id.

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

.. autofunction:: dallinger.realtime.realtime_sessions_for

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
