"""Real-time sessions, kept in redis while they're played.

Experiment code starts a session with :func:`create_realtime_session`, reads
its state with :func:`realtime_state` and ends it early with
:func:`end_realtime_session`. The rest of this module is for the web process
and the runners.

The real-time engine needs redis 7.0 or later.
"""

# Each session has these keys, under realtime:<session id>:
#
# - entries: a stream of the session's entries not yet applied, each a JSON
#   dict in the field "entry". An entry's ID gives the time it arrived.
# - state: a hash holding the session's "game" (its game type's channel), the
#   "saved" session from core.py, the "position" (the ID of the last entry
#   applied to it, if any) and how many entries have been "applied".
# - members: a hash from each player's participant id to 1 for a bot, 0
#   otherwise.
# - claim: the runner playing the session, as "<epoch>:<runner>". It expires
#   unless the runner renews it, and goes when the session ends.
# - epoch: counts the claims made on the session, so each claim's number is
#   higher than every earlier claim's.
# - unreleased: the token of the last claim, until its runner gives it up or
#   the session ends.
# - handovers: how many claims on the session in a row expired rather than
#   being given up, with no save in between.
# - records: a stream of the session's records for Postgres, each a JSON dict
#   in the field "record".
# - final: once the session has ended, its ending's "reason" and the final
#   "views" of the players who aren't bots, as JSON.
# - dropped: how many of the session's messages were over the rate limit.
#
# realtime:running is the set of sessions that haven't ended, and
# realtime:runners is a sorted set of the runners, each scored by the time its
# heartbeat expires.
#
# Redis 7.0 is needed for XINFO STREAM's count of the entries ever added. The
# save relies on a watched key that expires aborting the transaction that
# watches it.

import json

from redis import WatchError

from dallinger import db, experiment
from dallinger.db import redis_conn
from dallinger.models import RealtimeSession
from dallinger.realtime.core import new_session
from dallinger.realtime.game import validate_game_types
from dallinger.realtime.utils import dump_json
from dallinger.utils import normalized_participant_id

#: The most entries a session's stream keeps, and redis may keep a few more.
#: A session whose runner falls this far behind loses its oldest entries
#: unapplied, whatever their type, and :func:`lost_entries` counts them.
MAX_ENTRIES = 10000

RUNNING = "realtime:running"
RUNNERS = "realtime:runners"

# Redis runs each script as one command, so nothing else reaches its keys
# between the script's check and its change. KEYS and ARGV count from 1.
_claim = redis_conn.register_script(
    """
    -- SISMEMBER: whether the session is in the running set.
    if redis.call("exists", KEYS[1]) == 1
        or redis.call("sismember", KEYS[3], ARGV[3]) == 0 then
        return false
    end
    -- With no claim held, a claim not given up has expired.
    if redis.call("exists", KEYS[4]) == 1 then
        redis.call("incr", KEYS[5])
    end
    -- INCR starts a missing counter at 0, so the first epoch is 1.
    local token = redis.call("incr", KEYS[2]) .. ":" .. ARGV[1]
    -- PX: the key expires after this many milliseconds.
    redis.call("set", KEYS[1], token, "px", ARGV[2])
    redis.call("set", KEYS[4], token)
    -- GET returns false for a missing key.
    return {token, tonumber(redis.call("get", KEYS[5]) or 0)}
    """
)
_extend = redis_conn.register_script(
    """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        -- PEXPIRE sets a new expiry, in milliseconds, and returns 1.
        return redis.call("pexpire", KEYS[1], ARGV[2])
    end
    return 0
    """
)
_release = redis_conn.register_script(
    """
    if redis.call("get", KEYS[1]) == ARGV[1] then
        return redis.call("del", KEYS[1], KEYS[2])
    end
    return 0
    """
)


def session_key(session_id, name):
    return "realtime:{}:{}".format(session_id, name)


def experiment_games():
    """Return the running experiment's game types, from its
    :attr:`~dallinger.experiment.Experiment.realtime_games`, as a dict from
    each channel to an instance of its game type.

    :raises ValueError: as
        :func:`~dallinger.realtime.game.validate_game_types` does
    """
    experiment_class = experiment.load()
    return validate_game_types(
        experiment_class.realtime_games, experiment_class.channel
    )


def create_realtime_session(game_type, players, bots=()):
    """Start a session of ``game_type`` and return its session id, an
    integer.

    The session's :class:`~dallinger.models.RealtimeSession` row is
    committed in a transaction of its own, so the session has started when
    this returns, whatever happens to the caller's transaction. A runner
    picks it up and plays it until it ends.
    :mod:`dallinger.realtime.runner` says how to start one.

    :param game_type: one of the experiment's
        :attr:`~dallinger.experiment.Experiment.realtime_games`
    :param players: the participant ids of the session's players, bots
        included
    :param bots: the players the runner plays for, using
        :meth:`~dallinger.realtime.game.RealtimeGame.bot`, in the order they
        move
    :raises ValueError: if ``game_type`` isn't one of the experiment's game
        types, those game types are invalid, ``players`` is empty,
        ``players`` or ``bots`` has a value that isn't a participant id or
        repeats one, or a bot isn't one of the ``players``
    """
    channel = getattr(game_type, "channel", None)
    game = experiment_games().get(channel)
    if type(game) is not game_type:
        raise ValueError(
            "{!r} isn't one of the experiment's realtime_games.".format(game_type)
        )
    players = _participant_ids(players, "players")
    if not players:
        raise ValueError("A session needs at least one player.")
    bots = _participant_ids(bots, "bots")
    saved = new_session(game, players, bots)
    with db.session_factory() as own:
        row = RealtimeSession(
            game_type=channel,
            members=[int(player) for player in players],
            bots=[int(bot) for bot in bots],
        )
        own.add(row)
        own.commit()
        session_id = row.id
    # A pipeline runs as one transaction, so a runner never finds the session
    # in the running set before its state is there.
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


def clear_realtime_sessions():
    """Delete every session from redis, ended or not, keeping the runners'
    heartbeats. :func:`dallinger.db.init_db` calls this when it recreates the
    database, since session ids then start again at 1.
    """
    # SCAN walks the keyspace a batch at a time without blocking redis.
    keys = [
        key
        for key in redis_conn.scan_iter(match="realtime:*", count=1000)
        if key != RUNNERS.encode()
    ]
    for start in range(0, len(keys), 1000):
        redis_conn.delete(*keys[start : start + 1000])


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
    # HGETALL returns every field of a hash, or {} if there's no such key.
    members = redis_conn.hgetall(session_key(session_id, "members"))
    return {player.decode(): flag == b"1" for player, flag in members.items()}


def running_sessions():
    """Return the ids of the sessions that haven't ended."""
    # SMEMBERS returns a set's members in no particular order.
    return sorted(int(session_id) for session_id in redis_conn.smembers(RUNNING))


def load_session(session_id):
    """Return a session's ``game`` channel, ``saved`` session, stream
    ``position``, which is ``None`` before any entry is applied, and the
    number of entries ``applied``.

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
        "applied": int(fields.get(b"applied", 0)),
    }


def add_entry(session_id, entry):
    """Add an entry to a session's stream and return its ID.

    :param entry: a dict as :mod:`dallinger.realtime.core` describes, without
        its ``received``, which comes from the ID, or its ``time``, which
        the runner sets
    """
    # XADD returns the new entry's ID, "<milliseconds>-<sequence>" on redis's
    # clock. An approximate MAXLEN trims only whole blocks of old entries,
    # which is cheaper, so the stream can run a little over.
    entry_id = redis_conn.xadd(
        session_key(session_id, "entries"),
        {"entry": dump_json(entry)},
        maxlen=MAX_ENTRIES,
        approximate=True,
    )
    return entry_id.decode()


def read_entries(positions, timeout, count=None):
    """Wait up to ``timeout`` seconds for entries after the given positions,
    in one ``XREAD`` across the sessions' streams.

    :param positions: a dict from each session id to its stream position
    :param count: the most entries to read from each session's stream, or
        ``None`` for all of them
    :returns: a dict from each session id with new entries to a list of its
        ``(entry_id, fields)`` stream items, in order. An entry ID is a
        string.
    """
    keys = {session_key(session_id, "entries"): session_id for session_id in positions}
    streams = {key: positions[session_id] or "0-0" for key, session_id in keys.items()}
    # XREAD returns each stream's entries after the given ID, "0-0" for all of
    # them, waiting up to block milliseconds while none has any. It treats a
    # block of 0 as no timeout at all.
    block = _ms(timeout) if timeout > 0 else None
    read = {}
    # COUNT applies to each stream.
    for key, items in redis_conn.xread(streams, count=count, block=block) or []:
        read[keys[key.decode()]] = [
            (entry_id.decode(), fields) for entry_id, fields in items
        ]
    return read


def read_entry(entry_id, fields):
    """Return the entry a stream item holds, with the server clock time it
    was ``received``.
    """
    entry = json.loads(fields[b"entry"])
    entry["received"] = int(_id_text(entry_id).split("-")[0]) / 1000
    return entry


def lost_entries(applied):
    """Count the entries each session's stream dropped before they were
    applied, because the stream reached :data:`MAX_ENTRIES`.

    :param applied: a dict from the id of each session that has had entries
        to the number of entries applied to it, as :func:`load_session` gives
        it and the runner's own saves since then add to it
    :returns: a dict from each of those session ids to its count
    """
    with redis_conn.pipeline(transaction=False) as pipe:
        for session_id in applied:
            pipe.xinfo_stream(session_key(session_id, "entries"))
        infos = pipe.execute()
    # XINFO STREAM's entries-added counts every entry the stream ever had,
    # trimmed ones included. A save removes exactly the entries it applied,
    # so the stream holds every entry added and not yet applied unless MAXLEN
    # trimmed some of them.
    return {
        session_id: info["entries-added"] - count - info["length"]
        for (session_id, count), info in zip(applied.items(), infos)
    }


def count_dropped(session_id, count=1):
    """Add ``count`` to the session's dropped messages and return the total."""
    # INCRBY starts a missing counter at 0.
    return redis_conn.incrby(session_key(session_id, "dropped"), count)


def claim(session_id, runner, ttl):
    """Claim a session for ``runner`` for ``ttl`` seconds.

    The checks, the new epoch and the claim run as one redis script, so
    they're atomic.

    A claim made after the previous one expired, rather than being given up
    with :func:`release_session_claims`, is a handover.

    :returns: ``None`` if another claim holds the session or it has ended.
        Otherwise the claim's token, a string, and the number of the
        session's handovers since it was last saved, this claim's included.
    """
    claimed = _claim(
        keys=[
            session_key(session_id, "claim"),
            session_key(session_id, "epoch"),
            RUNNING,
            session_key(session_id, "unreleased"),
            session_key(session_id, "handovers"),
        ],
        args=[runner, _ms(ttl), session_id],
    )
    if claimed is None:
        return None
    token, handovers = claimed
    return token.decode(), handovers


def extend_session_claims(tokens, ttl):
    """Extend each claim still held to ``ttl`` seconds from now, in one round
    trip, and return the ids of the sessions whose claims were lost.

    Each claim's check and change run as one redis script, so they're atomic.

    :param tokens: a dict from each session id to its claim's token
    """
    with redis_conn.pipeline(transaction=False) as pipe:
        for session_id, token in tokens.items():
            _extend(
                keys=[session_key(session_id, "claim")],
                args=[token, _ms(ttl)],
                client=pipe,
            )
        extended = pipe.execute()
    return [session_id for session_id, held in zip(tokens, extended) if not held]


def check_redis():
    """Raise :class:`RuntimeError` unless redis is version 7.0 or later."""
    version = redis_conn.info("server")["redis_version"]
    if int(version.split(".")[0]) < 7:
        raise RuntimeError(
            "The real-time engine needs redis 7.0 or later, not {}.".format(version)
        )


def server_time():
    """Return redis's clock, which stamps entry IDs, in seconds since the
    epoch.
    """
    seconds, microseconds = redis_conn.time()
    return seconds + microseconds / 1e6


def release_session_claims(tokens):
    """Give up each claim still held, in one round trip, and return the ids of
    the sessions whose claims were lost.

    Each claim's check and change run as one redis script, so they're atomic.

    :param tokens: a dict from each session id to its claim's token
    """
    with redis_conn.pipeline(transaction=False) as pipe:
        for session_id, token in tokens.items():
            _release(
                keys=[
                    session_key(session_id, "claim"),
                    session_key(session_id, "unreleased"),
                ],
                args=[token],
                client=pipe,
            )
        released = pipe.execute()
    return [session_id for session_id, held in zip(tokens, released) if not held]


def mark_runner_alive(runner, clock, ttl):
    """Record that ``runner`` is running until ``ttl`` seconds after
    ``clock``, a time on redis's clock, and return the names of the runners
    that are.
    """
    with redis_conn.pipeline(transaction=False) as pipe:
        pipe.zadd(RUNNERS, {runner: clock + ttl})
        # ZREMRANGEBYSCORE removes the members with scores in a range.
        pipe.zremrangebyscore(RUNNERS, "-inf", clock)
        # ZRANGE 0 -1 returns every member.
        pipe.zrange(RUNNERS, 0, -1)
        return sorted(name.decode() for name in pipe.execute()[-1])


def remove_runner(runner):
    """Record that ``runner`` has stopped."""
    redis_conn.zrem(RUNNERS, runner)


def save_passes(passes, ttl):
    """Save passes of several sessions in one transaction, if their claims are
    still held, and extend those claims to ``ttl`` seconds.

    :param passes: a ``(session_id, token, applied, result)`` tuple for each
        session, where ``applied`` lists the IDs of the entries the pass
        applied, in order, and ``result`` is the pass's
        :class:`~dallinger.realtime.core.PassResult`
    :returns: the ids of the sessions whose claims were lost, which weren't
        saved

    Each session's saved session, position and count of applied entries are
    written, its records added, its applied entries removed, and its count
    of handovers started again. A session
    the pass ended leaves the running set, gets its final views, and gives up
    its claim. A claim that changes or expires while the transaction is
    prepared aborts it, and it's tried again without the sessions whose
    claims were lost.
    """
    pending = list(passes)
    lost = []
    px = _ms(ttl)
    while pending:
        claim_keys = [session_key(each[0], "claim") for each in pending]
        with redis_conn.pipeline() as pipe:
            # WATCH makes EXEC raise WatchError if a watched key changes or
            # expires first. Until MULTI, the pipeline runs each command at
            # once, so MGET reads the claims as they are now.
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
            # From MULTI on, commands wait for EXEC and run together.
            pipe.multi()
            for session_id, _, applied, result in pending:
                _write_pass(pipe, session_id, applied, result, px)
            try:
                pipe.execute()
            except WatchError:
                continue
        break
    return lost


def _write_pass(pipe, session_id, applied, result, px):
    state_key = session_key(session_id, "state")
    state = {"saved": result.saved}
    if applied:
        state["position"] = applied[-1]
        # XTRIM with MINID removes the entries with lower IDs: those applied.
        pipe.xtrim(
            session_key(session_id, "entries"),
            minid=_next_id(applied[-1]),
            approximate=False,
        )
        # HINCRBY adds to a number in a hash field, starting a missing one at 0.
        pipe.hincrby(state_key, "applied", len(applied))
    pipe.hset(state_key, mapping=state)
    pipe.delete(session_key(session_id, "handovers"))
    for record in result.records:
        pipe.xadd(session_key(session_id, "records"), {"record": dump_json(record)})
    if result.ended is None:
        # PEXPIRE sets a new expiry, in milliseconds.
        pipe.pexpire(session_key(session_id, "claim"), px)
    else:
        pipe.delete(
            session_key(session_id, "claim"), session_key(session_id, "unreleased")
        )
        # SREM takes the session out of the running set.
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
    # Redis rejects a PX of 0, and a PEXPIRE of 0 deletes the key.
    return max(1, round(seconds * 1000))
