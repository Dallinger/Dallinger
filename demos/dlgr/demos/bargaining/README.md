# Bargaining

Pairs of participants bargain over the price of one item, in a real-time game.
One player is the seller, with a private cost, and the other is the buyer, with
a private value. Either can make or change an offer at any time, or accept the
other's, until the clock runs out. Settings add more rounds and a chat between
the two players.

The demo is a small, complete example of a real-time experiment, written for
researchers who want to build one of their own. This page walks through how
it works. The engine itself is described in
[Real-Time Games](https://dallinger.readthedocs.io/en/latest/realtime_games.html),
and the page's helpers in the
[real-time sessions section of the JavaScript API](https://dallinger.readthedocs.io/en/latest/javascript_api.html#real-time-sessions).

## The Game

The seller's cost is drawn from 10 to 60 cents, and the buyer's value from 40
to 90, so some pairs have no price that leaves both of them better off. Prices
are whole cents from 0 to 100.

- Each player can post an offer at any time, and replace it with a new one. An
  offer that would lose its player money is refused.
- Either player can accept the other's standing offer, unless the price would
  lose them money. A deal pays the seller the price minus their cost, and the
  buyer their value minus the price, and ends the round.
- If time runs out first, neither player earns anything.

Each player sees their own role and value, both standing offers, every offer
so far and the time left. The other player's value is shown only once the
round is over. Each player's bonus is their earnings over every round.

## Settings

The settings go in the `[Experiment]` section of `config.txt`:

| Setting | Default | What it does |
|---|---|---|
| `pairs` | `1` | How many pairs to recruit |
| `bargaining_seconds` | `60` | How long each round lasts, once both players are there |
| `rounds` | `1` | How many rounds each pair plays, each with new roles and values |
| `chat` | `false` | Let the two players chat while they bargain |

Settings can also be given as environment variables, to try one without
editing `config.txt`:

    rounds=3 chat=true dallinger debug

The instructions and game pages follow the settings, so they describe the
length of a round, the number of rounds and the chat only when they apply.

## How It's Built

The demo has three parts:

- **`Bargain`**, in `experiment.py`, is the game type: the rules of one round.
- **`Bargaining`**, in `experiment.py`, is the experiment: it pairs
  participants, starts their rounds, saves the chat and pays the bonus.
- **The page**, `static/scripts/experiment.js` with the templates, shows each
  round to the player.

### The Game Type

A game type's methods are plain functions of the game's state, a JSON object
Dallinger keeps for each round. Dallinger calls them as players act and time
passes, and saves what happens. They don't use the database or the network,
which makes them easy to test; `demos/tests/test_bargaining.py` shows how.

- `initial_state` draws the roles and values for a new round.
- `apply` handles each message a page sends, `{"offer": price}` or
  `{"accept": price}`. It changes the state, or raises `Reject` with a reason
  the player sees. An accept names the price it accepts, so if the other
  player changed their offer a moment before, the accept is refused instead
  of agreeing to a price the player never saw.
- `is_over` says when the round has ended: on a deal, or when time runs out.
- `outcome` is what's saved when the round ends: the roles, the values, the
  deal and each player's earnings.

### Hidden Information

Pages never see the state, only what `view` returns for their player. The
view leaves out the other player's value until the round is over, so it stays
hidden however the page is written or tampered with.

### The Clock

Nothing happens between messages except the clock running down, so the game
has no ticks. Instead `next_deadline` tells Dallinger when the next thing
happens on its own, and Dallinger calls `tick` then. A game where things move
all the time, like the coins demo, sets a `tick_rate` instead.

A round starts as soon as the pair is complete, which can be before both pages
have opened. So that neither player loses time, the clock waits until both are
there. Dallinger calls `on_join` when a player's page opens, and for a bot,
which has no page, as the round starts. Once both are there, the game sets
the deadline `bargaining_seconds` later. If someone
still hasn't arrived after `JOIN_SECONDS` (30), the clock starts anyway, so a
player who never opens the page can't hold the round open. The page counts
down from the deadline in the view.

### Starting a Round and Paying the Bonus

Each pair is a network of two. When the second player joins,
`add_node_to_network` calls `create_realtime_session`, which starts the
pair's first round. Players recruited as bots, like the demo's `Bot`, never
open the page, so they're listed as `bots`, and Dallinger plays for them with
the game type's `bot` method.

`bonus` reads the pair's rounds with `realtime_sessions_for` and adds up the
player's earnings from every round that ended normally.

### Rounds

Each round is a session of its own, with its own record and outcome, and new
roles and values. Starting a session writes to the database, which game
methods can't do, so when a round ends with a deal or at its deadline, the game
queues an effect named `bargain_over`. Dallinger passes it to `handle_effect`
on a worker, which starts the next round if the pair has played fewer than
`rounds`. An error there would also undo saving the round just played, so
`handle_effect` logs a failure to start the next round instead.

Dallinger saves the next round no later than the end of the last one. So when
a page learns that a round's result is saved, the next round is already
there, and the page joins it, passing the round it just played as
`afterSession` so that only a newer one counts. A bot's wait for its rounds
lasts through all of them for the same reason.

A round can also end another way, for example if the game's code fails or the
experimenter stops it. No next round starts then, and the page lets the
player move on to the questionnaire. It also does that if a next round it
expects hasn't arrived within ten seconds.

### Chat

With `chat` on, the page joins each round through the `/chat` route, with
`waitForRealtimeSession` and `openChatSocket`, so the same socket carries both
the game and the chat. Chat goes to the experiment, not the game: the page
sends it to the experiment's channel, `bargain_chat`, and it never reaches
`apply`.

`receive_message` runs on a worker for each message. It checks that the sender
is one of the round's players, saves the message as an `Info` on the sender's
node, and once that's saved, sends it to both players with
`publish_to_participants`. A player's own message appears when it comes back,
so what they see is what was saved. A bot can't type, so the experiment
answers for it in the manner of the ELIZA chatbot, turning the player's words
around without understanding them, so it gives nothing away about the
bargain.

Two limits matter for a real study. The page names the sender, and nothing
checks it, so a player could post as their partner. And any page can
subscribe to the `bargain_chat` channel and read what every pair sends: the
copies sent back go only to the pair, but the messages on their way in don't.
See [Using WebSockets](https://dallinger.readthedocs.io/en/latest/using_websockets.html)
for the routes and directed messages.

### The Page

The instructions page creates the participant and their node, which may start
the pair's first round. The game page then joins it with
`dallinger.joinRealtimeSession`, or with chat on, `waitForRealtimeSession` and
`openChatSocket`. Joining finds a running round again after a reload, and the
page keeps its round count in the tab's `sessionStorage`, so a reloaded page
still shows the right round number.

The socket's callbacks drive the page: `onView` redraws it from each new view,
`onRejected` shows why a message didn't count, `onEnded` shows the result, and
`resultSaved` waits until the outcome is saved before the page moves on, to
the next round or to the questionnaire.

## Playing With Bots

Bots are players the game plays for. A bot accepts an offer that earns it at
least 5 cents, and otherwise concedes 5 cents for every offer the other player
makes. With chat on, it answers every message, as described above. Bots
answer each other at once, so two bots play a whole round the moment it
starts.

A bot waits up to ten minutes for its rounds to end, the default of
`wait_for_realtime_sessions`, then signs off, even partway through a series.
For more rounds than fit in ten minutes, pass a longer `timeout` to it in
`Bot.participate`.

To watch bots play each other, run:

    dallinger debug --bot

To bargain against a bot yourself, say how many players come from each
recruiter:

    [Experiment]
    recruiter = multi
    recruiters = hotair: 1, bots: 1

Then run `dallinger debug`. It opens a window for you, and the round starts as
soon as you click Begin.

## What's Saved

Each round is a session, with a row in the `realtime_session` table. Its
`outcome` holds the round's results, keyed by participant id:

    {"roles": {"1": "buyer", "2": "seller"},
     "values": {"1": 71, "2": 18},
     "deal": 23,
     "earnings": {"1": 48, "2": 5}}

`deal` is `null` when time ran out. The round's record is in the
`realtime_event` table, one row per event: every offer and accept, including
those the game refused, with the reason; the `bargain_over` effects; a copy
of the state every five seconds; the ending, with the final state; and clock
measurements from each page.

This lists every round with its deal, oldest first:

    SELECT id, members, outcome->'deal' AS deal, outcome->'earnings' AS earnings
    FROM realtime_session ORDER BY id;

With chat on, each message is an `Info` in the `info` table, on the sender's
node, with the text as its `contents` and the round's session id in its
`details`:

    SELECT origin_id, contents, details->'session' AS session, creation_time
    FROM info ORDER BY id;

All of these tables are exported with the rest of the experiment's data.

### Response Times

Each offer and accept has a row in `realtime_event` with `event_type`
`message`, and three times:

- `session_time`: when the game applied it, in seconds on the round's own
  clock, which stops while a game is paused. The gap between one player's
  offer and the other's reply is the response time as the server saw it,
  including each message's trip over the network, usually tens of
  milliseconds.
- `browser_time`: when the player's page sent it, on that player's browser
  clock, in seconds since 1970. Two times from the same page compare exactly,
  such as the gap between a player's own offers. To compare them with the
  other player or the server, put them on the server's clock: each `clock`
  row from that page pairs a `browser_time` with the server's `server_time`,
  in its `payload`, so their difference is the page's clock offset, accurate
  to within half the `payload`'s `round_trip`.
- `view_time`: the session time of the view the page was showing when the
  player acted. If it's earlier than the `session_time` of the other player's
  latest offer, the player hadn't seen that offer yet.

The page doesn't record when it showed each view. A study that needs the time
from an offer appearing to the reply can have the page send that moment with
the reply, from `dallinger.browserTime()`.

This lists every message with its times, round by round:

    SELECT session_id, participant_id, payload, status,
           session_time, view_time, browser_time
    FROM realtime_event WHERE event_type = 'message'
    ORDER BY session_id, sequence;
