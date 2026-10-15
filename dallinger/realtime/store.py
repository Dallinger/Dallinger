"""Real-time sessions in redis.

Experiment code starts a session with :func:`create_realtime_session`, reads
its state with :func:`realtime_state` and ends it early with
:func:`end_realtime_session`. The rest of this module is for the web process
and the runners.

Each session has these keys, under ``realtime:<session id>:``:

- ``entries``: a stream of the session's entries not yet applied, each a
  JSON dict in the field ``entry``. An entry's ID gives the time it arrived.
- ``state``: a hash holding the session's ``game`` (its game type's channel),
  the ``saved`` session from :mod:`dallinger.realtime.core`, and the
  ``position``: the ID of the last entry applied to it, if any.
- ``members``: a hash from each player's participant id to ``1`` for a bot,
  ``0`` otherwise.
- ``claim``: the runner playing the session, as ``<epoch>:<runner>``. It
  expires unless the runner renews it.
- ``epoch``: counts the claims made on the session, so each claim's number
  is higher than every earlier claim's.
- ``records``: a stream of the session's records for Postgres, each a JSON
  dict in the field ``record``.
- ``final``: once the session has ended, its ending's ``reason`` and the
  final ``views`` of the players who aren't bots, as JSON.
- ``dropped``: how many of the session's messages were over the rate limit.

``realtime:session_ids`` counts the sessions created, and
``realtime:running`` is the set of sessions that haven't ended.

The store needs redis 6.2 or later, for ``XTRIM`` with ``MINID``, and relies
on a watched key that expires aborting the transaction that watches it.
"""

import json

from redis import WatchError

from dallinger.db import redis_conn
from dallinger.realtime.core import new_session
from dallinger.realtime.game import validate_game_types
from dallinger.realtime.utils import dump_json
from dallinger.utils import normalized_participant_id

#: The most entries a session's stream keeps, and redis may keep a few more.
#: A session whose runner falls this far behind loses its oldest entries
#: unapplied, whatever their type, and nothing counts them.
MAX_ENTRIES = 10000

SESSION_IDS = "realtime:session_ids"
RUNNING = "realtime:running"

_claim = redis_conn.register_script(
    """
    if redis.call("exists", KEYS[1]) == 1 then
        return false
    end
    local token = redis.call("incr", KEYS[2]) .. ":" .. ARGV[1]
    redis.call("set", KEYS[1], token, "px", ARGV[2])
    return token
    """
)
_renew = redis_conn.register_script(
    """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("pexpire", KEYS[1], ARGV[2])
    end
    return 0
    """
)
_release = redis_conn.register_script(
    """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1])
    end
    return 0
    """
)


def session_key(session_id, name):
    return "realtime:{}:{}".format(session_id, name)


def create_realtime_session(game_type, players, bots=()):
    """Start a session of ``game_type`` and return its session id, an
    integer.

    Runners pick up the new session and play it until it ends.

    :param game_type: a :class:`~dallinger.realtime.game.RealtimeGame`
        subclass
    :param players: the participant ids of the session's players, bots
        included
    :param bots: the players the runner plays for, using
        :meth:`~dallinger.realtime.game.RealtimeGame.bot`, in the order they
        move
    :raises ValueError: if ``game_type`` is invalid, ``players`` is empty,
        ``players`` or ``bots`` has a value that isn't a participant id or
        repeats one, or a bot isn't one of the ``players``
    """
    ((channel, game),) = validate_game_types([game_type]).items()
    players = _participant_ids(players, "players")
    if not players:
        raise ValueError("A session needs at least one player.")
    bots = _participant_ids(bots, "bots")
    saved = new_session(game, players, bots)
    session_id = redis_conn.incr(SESSION_IDS)
    with redis_conn.pipeline() as pipe:
        pipe.hset(
            session_key(session_id, "state"), mapping={"game": channel, "saved": saved}
        )
        pipe.hset(
            session_key(session_id, "members"),
            mapping={player: int(player in bots) for player in players},
        )
        pipe.sadd(RUNNING, session_id)
        pipe.execute()
    return session_id


def _participant_ids(values, what):
    ids = []
    for value in values:
        participant_id = normalized_participant_id(value)
        if participant_id is None:
            raise ValueError(
                "{!r} in the {} isn't a participant id.".format(value, what)
            )
        ids.append(participant_id)
    if len(set(ids)) < len(ids):
        raise ValueError("The {} repeat a participant id.".format(what))
    return ids


def end_realtime_session(session_id, reason):
    """End a session that hasn't ended yet.

    The session ends after the messages that arrived before this call, and
    ``reason`` is passed to
    :meth:`~dallinger.realtime.game.RealtimeGame.outcome`. A session that has
    already ended keeps its ending.

    :param reason: why the session ended, a non-empty string
    :raises ValueError: if ``reason`` isn't a non-empty string
    :raises KeyError: if there is no session ``session_id``
    """
    if not isinstance(reason, str) or not reason:
        raise ValueError("An ending's reason must be a non-empty string.")
    if not redis_conn.exists(session_key(session_id, "state")):
        raise KeyError(session_id)
    if redis_conn.sismember(RUNNING, session_id):
        add_entry(session_id, {"type": "end", "reason": reason})


def realtime_state(session_id):
    """Return a session's state as a runner last saved it, which can be a
    moment behind the game.

    :raises KeyError: if there is no session ``session_id``
    """
    return json.loads(load_session(session_id)["saved"])["state"]


def session_members(session_id):
    """Return a dict from each player's participant id to whether it's a bot."""
    members = redis_conn.hgetall(session_key(session_id, "members"))
    return {player.decode(): flag == b"1" for player, flag in members.items()}


def running_sessions():
    """Return the ids of the sessions that haven't ended."""
    return sorted(int(session_id) for session_id in redis_conn.smembers(RUNNING))


def load_session(session_id):
    """Return a session's ``game`` channel, ``saved`` session and stream
    ``position``, which is ``None`` before any entry is applied.

    :raises KeyError: if there is no session ``session_id``
    """
    fields = redis_conn.hgetall(session_key(session_id, "state"))
    if not fields:
        raise KeyError(session_id)
    position = fields.get(b"position")
    return {
        "game": fields[b"game"].decode(),
        "saved": fields[b"saved"].decode(),
        "position": None if position is None else position.decode(),
    }


def add_entry(session_id, entry):
    """Add an entry to a session's stream and return its ID.

    :param entry: a dict as :mod:`dallinger.realtime.core` describes, without
        its ``received``, which comes from the ID, or its ``time``, which
        the runner sets
    """
    entry_id = redis_conn.xadd(
        session_key(session_id, "entries"),
        {"entry": dump_json(entry)},
        maxlen=MAX_ENTRIES,
        approximate=True,
    )
    return entry_id.decode()


def read_entry(entry_id, fields):
    """Return the entry a stream item holds, with the server clock time it
    was ``received``.
    """
    entry = json.loads(fields[b"entry"])
    entry["received"] = int(_id_text(entry_id).split("-")[0]) / 1000
    return entry


def count_dropped(session_id, count=1):
    """Add ``count`` to the session's dropped messages and return the total."""
    return redis_conn.incrby(session_key(session_id, "dropped"), count)


def claim(session_id, runner, ttl):
    """Claim a session for ``runner`` for ``ttl`` seconds.

    The check, the new epoch and the claim run as one redis script, so
    they're atomic.

    :returns: the claim's token, a string, or ``None`` if another claim holds
        the session
    """
    token = _claim(
        keys=[session_key(session_id, "claim"), session_key(session_id, "epoch")],
        args=[runner, _ms(ttl)],
    )
    return None if token is None else token.decode()


def renew(session_id, token, ttl):
    """Extend a claim to ``ttl`` seconds from now, returning whether the claim
    was still held.

    The check and the change run as one redis script, so they're atomic.
    """
    return bool(_renew(keys=[session_key(session_id, "claim")], args=[token, _ms(ttl)]))


def release(session_id, token):
    """Give up a claim, returning whether it was still held.

    The check and the change run as one redis script, so they're atomic.
    """
    return bool(_release(keys=[session_key(session_id, "claim")], args=[token]))


def save_passes(passes, ttl):
    """Save passes of several sessions in one transaction, if their claims are
    still held, and renew those claims to ``ttl`` seconds.

    :param passes: a ``(session_id, token, position, result)`` tuple for each
        session, where ``position`` is the ID of the last entry the pass
        applied, or ``None`` if it applied none, and ``result`` is the pass's
        :class:`~dallinger.realtime.core.PassResult`
    :returns: the ids of the sessions whose claims were lost, which weren't
        saved

    Each session's saved session and position are written, its records added,
    and its applied entries removed. A session the pass ended leaves the
    running set and gets its final views. A claim that changes while the
    transaction is prepared aborts it, and it's tried again without the
    sessions whose claims were lost. Renewing one of these claims elsewhere
    during the save also changes it, so the save is tried again.
    """
    pending = list(passes)
    lost = []
    px = _ms(ttl)
    while pending:
        claim_keys = [session_key(each[0], "claim") for each in pending]
        with redis_conn.pipeline() as pipe:
            pipe.watch(*claim_keys)
            still_held = []
            for each, value in zip(pending, pipe.mget(claim_keys)):
                if value is not None and value.decode() == each[1]:
                    still_held.append(each)
                else:
                    lost.append(each[0])
            if len(still_held) < len(pending):
                pending = still_held
                continue
            pipe.multi()
            for session_id, _, position, result in pending:
                _write_pass(pipe, session_id, position, result, px)
            try:
                pipe.execute()
            except WatchError:
                continue
        break
    return lost


def _write_pass(pipe, session_id, position, result, px):
    state = {"saved": result.saved}
    if position is not None:
        state["position"] = position
        pipe.xtrim(
            session_key(session_id, "entries"),
            minid=_next_id(position),
            approximate=False,
        )
    pipe.hset(session_key(session_id, "state"), mapping=state)
    for record in result.records:
        pipe.xadd(session_key(session_id, "records"), {"record": dump_json(record)})
    pipe.pexpire(session_key(session_id, "claim"), px)
    if result.ended is not None:
        pipe.srem(RUNNING, session_id)
        pipe.set(
            session_key(session_id, "final"),
            dump_json(
                {"reason": result.ended["reason"], "views": result.ended["views"]}
            ),
        )


def _id_text(entry_id):
    return entry_id.decode() if isinstance(entry_id, bytes) else entry_id


def _next_id(entry_id):
    # XTRIM's MINID keeps entries from the given ID on.
    ms, sequence = _id_text(entry_id).split("-")
    return "{}-{}".format(ms, int(sequence) + 1)


def _ms(seconds):
    return max(1, round(seconds * 1000))
