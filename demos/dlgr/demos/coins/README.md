# Coins

Two to four players race around an arena collecting coins, all at the same
time, in a one-minute real-time game. Each coin earns a bonus, 2 cents by
default. Settings let players steal from each other, bounce off each other, or
play against bots, from easy to as fast as you.

The game is played by Dallinger's real-time engine, as described in
[Real-Time Games](https://dallinger.readthedocs.io/en/latest/realtime_games.html).

## Playing

Each player is a pixel invader: a red squid, a blue crab, a green octopus or a
purple saucer, in the order the players signed up. Yours sits on a faint tile of
its own color. Move with the arrow keys, or with W, A, S and D, and run over a
coin to collect it. The game starts with three coins, another appears every
two seconds until there are six, and it ends after a minute.

Every player moves at the same speed, however fast their keyboard or
connection. The page sends the game which way you moved and for how long, and
the game counts that time against its own clock, so a page can't move a player
any faster than the rules allow.

The game's page demonstrates two optional features of Dallinger's real-time
client, prediction and interpolation, which make every player's movement
smooth. A game page works without them too.

If the game pauses, for example while Dallinger moves it to another process,
the page says "Paused…" and carries on from where it stopped.

## Settings

The settings go in the `[Experiment]` section of `config.txt`:

| Setting | Default | What it does |
|---|---|---|
| `groups` | `1` | How many games to run, each with its own group of players |
| `players_per_group` | `2` | Players in each game, from 2 to 4 |
| `stealing` | `false` | Run into another player to take one of their coins |
| `bouncing` | `false` | Run into another player to knock them away |
| `bounce_distance` | `1.0` | How far a knock sends a player, beyond touching |
| `bot_speed` | `0.8` | How fast bots move, as a share of a player's speed |
| `bonus_per_coin` | `0.02` | The bonus each coin earns, in dollars |

### Stealing and Bouncing

With `stealing` or `bouncing` on, players can touch. What happens depends on
who was heading toward whom:

- When one player runs into another, they take one of the other's coins, with
  `stealing` on, and knock them away, with `bouncing` on. The player who ran in
  stops where they touched.
- When both are heading into each other, neither steals, and both bounce apart.
- A player who has just been robbed blinks, and can't be robbed again for two
  seconds.
- Players who are already touching have to part before they can touch again.

The instructions and the game page explain whichever rules are on, and the
end of the game tells each player how many coins they stole and lost, and how
many times they were bounced and bounced others.

## Playing With Bots

Bots are players the game plays for, by the same rules as everyone else.
`bot_speed` sets how fast they go: the default `0.8` gives a person a fair
chance, `0.5` is an easy game, and `1.0` is as fast as a person. A value above
1 changes nothing, because the game holds every player to the same maximum
speed.

To watch bots play each other, run:

    dallinger debug --bot

To play against bots yourself, set the group size and say how many players
come from each recruiter, here one person and two bots:

    [Experiment]
    players_per_group = 3
    recruiter = multi
    recruiters = hotair: 1, bots: 2

Then run `dallinger debug`. It opens a window for you, and the game starts as
soon as you click Begin.

Settings can also be given as environment variables, to try one without
editing `config.txt`:

    stealing=true bouncing=true dallinger debug --bot

## What's Saved

Each game is a session, with a row in the `realtime_session` table. Its
`outcome` holds each player's results, keyed by participant id:

    {"coins": {"1": 9, "2": 5, "3": 18},
     "stole": {"1": 4, "2": 3, "3": 6},
     "coins_lost": {"1": 5, "2": 6, "3": 2},
     "bounced": {"1": 18, "2": 18, "3": 10},
     "bounced_others": {"1": 17, "2": 13, "3": 16}}

Each player's bonus, `bonus_per_coin` for each coin, is paid from `coins` once
the game's ending is saved.

The game's record is in the `realtime_event` table, one row per event, in the
order they happened:

- **Coin pickups and touches.** Pages send many moves a second, so the game
  keeps only the moves that collected a coin or touched another player. That
  keeps the record small, but it can't replay where players went between
  checkpoints. A game type that saves every move, which is the default, and
  draws its random numbers from a seed in its state can be replayed exactly.
- **Steals and bounces**, as effects named `steal` and `bounce`. Each payload
  says who did it to whom and where:
  `{"by": "1", "from": "2", "at": [6.28, 5.41]}` for a steal, and
  `{"by": "1", "bounced": "2", "at": [6.28, 5.41]}` for a bounce.
- **Checkpoints**, a copy of the game every five seconds.
- **The ending**, with its reason, the outcome and the final state.
- **Clock measurements** from each page, for putting the times browsers report
  on the server's clock.

This lists every steal, with its time on the game's clock:

    SELECT session_time, payload FROM realtime_event
    WHERE event_type = 'effect' AND name = 'steal';

The steals and bounces are also in the `info` table, each as an `Info` on the
node of the player who did it, with the effect's name as its `contents` and
its payload as its `details`.

All of these tables are exported with the rest of the experiment's data.
