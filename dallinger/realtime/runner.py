"""The runner, the process that plays real-time sessions.

An experiment with :attr:`~dallinger.experiment.Experiment.realtime_games`
needs a runner beside its web and worker processes. The ``dallinger_realtime``
command starts one in the experiment's directory. It loads the experiment,
plays every running session of the experiment's game types, and sends each
player's page its views, until it gets ``SIGTERM`` or ``SIGINT``.

Several runners can play one experiment's sessions, and each session is
played by one runner at a time. Each session belongs to one of the running
runners, picked by hashing the session's id with each runner's name, so the
runners split the sessions about evenly without coordinating. When a runner
starts or stops, only the sessions that belong to it move. A session's time
stops while no runner is playing it.

A runner that gets ``SIGTERM`` or ``SIGINT`` plays and saves its sessions one
last time, for up to :data:`SHUTDOWN_PLAY_TIME` seconds, and gives them up as
it stops. Other runners take them over at once, from that moment, and a
runner giving sessions to one that started does the same. A runner that stops
any other way, because it was killed or game code caught every exception in a
loop, leaves its sessions to be taken over after about :data:`CLAIM_TTL`
seconds. A session that changes runners that way
:data:`MAX_HANDOVERS` times within :data:`HANDOVER_WINDOW` seconds fails, so
one session can't stop every runner in turn.

The runner logs at the experiment's ``loglevel_worker``. It logs each session
that fails, with its error.

If the runner loses its connection to redis, it logs that, stops playing, and
tries again every :data:`REDIS_RETRY_INTERVAL` seconds. Once redis is back, it
goes on playing its sessions from where they were last saved. An outage
affects every runner alike, so a runner that's back waits
:data:`HEARTBEAT_TTL` seconds before claiming sessions it didn't hold, for
the others to say they're running again. A session whose claim expired during
the outage then goes back to the runner it belongs to, and a runner taking back
a claim it held itself doesn't count toward :data:`MAX_HANDOVERS`.

The runner also warns when it isn't keeping up: when playing its sessions
once and sending their views takes longer than the time between ticks of the
fastest game among them, or :data:`SLOW` seconds when none of them has ticks.
The warning names the sessions that took longest, so slow game code shows up
while testing. It comes at most every :data:`SLOW_LOG_INTERVAL` seconds.
"""

import hashlib
import logging
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass

from redis import ConnectionError as RedisConnectionError
from redis import RedisError
from redis import TimeoutError as RedisTimeoutError

from dallinger.db import get_queue
from dallinger.realtime import store
from dallinger.realtime.core import fail_session, run_pass, session_time
from dallinger.realtime.delivery import publish_views
from dallinger.realtime.game import FAILED
from dallinger.realtime.jobs import write_records

logger = logging.getLogger(__name__)

#: A runner claims each session it plays, so that no other runner plays it at
#: the same time. The claim lasts this many seconds unless the runner renews
#: it, so another runner takes the session over this long after its runner
#: stops.
CLAIM_TTL = 5

#: The longest a runner leaves a session's claim before renewing it, in
#: seconds. A session whose game code runs for longer than ``CLAIM_TTL`` less
#: this without a break can lose its claim, and another runner then plays it
#: from where it was last saved.
SESSION_RENEW_INTERVAL = CLAIM_TTL / 3

#: Seconds between a runner's checks for sessions no runner is playing, which
#: also tell the other runners it's running.
CLAIM_INTERVAL = 0.5

#: Seconds after a runner last said it's running that the other runners
#: take its sessions over.
HEARTBEAT_TTL = CLAIM_TTL

#: How many times a session may change runners within
#: :data:`HANDOVER_WINDOW` seconds before it fails. Only runners that stopped
#: without giving the session up count.
MAX_HANDOVERS = 3

#: Seconds over which a session's changes of runner are counted.
HANDOVER_WINDOW = 60

#: The most entries a pass applies to one session. A session with more
#: waiting, after a takeover or a slow pass, gets the rest in the passes that
#: follow, so a backlog doesn't use up its game type's time limit.
MAX_PASS_ENTRIES = 100

#: Seconds a stopping runner spends playing its sessions one last time. It
#: gives up the ones it hasn't played as they were last saved. A pass that
#: starts before then can still run its three time limits, so this and those
#: fit in the ten seconds Docker waits after ``SIGTERM`` before it kills a
#: process.
SHUTDOWN_PLAY_TIME = 3

#: Seconds between the jobs a runner queues to write each session's new
#: records.
RECORDS_INTERVAL = 2

#: The longest a player's message, or a page opening or closing, may wait for
#: a runner, in seconds, before its session fails. A runner taking over a
#: session from one that stopped takes up to about :data:`CLAIM_TTL`.
MAX_ENTRY_WAIT = 4 * CLAIM_TTL

#: Seconds the runner may take to play sessions whose games have no ticks
#: before it warns that it isn't keeping up.
SLOW = 1

#: The fewest seconds between two of the runner's warnings about slow steps.
SLOW_LOG_INTERVAL = 10

#: Seconds a runner that lost its connection to redis waits before trying
#: again.
REDIS_RETRY_INTERVAL = 1


class _BetweenTimeLimits(BaseException):
    """Carries a redis error out of the core, which fails the session being
    played on an :class:`Exception`.
    """

    def __init__(self, error):
        super().__init__(error)
        self.error = error


@dataclass
class _Session:
    """A session a runner holds the claim on.

    ``game`` is ``None`` when the session has to end without game code: no
    game type has its ``channel``, or it changed runners more than
    :data:`MAX_HANDOVERS` times.
    ``renewed``, ``origin`` (session time 0) and ``next_pass`` are times on
    the runner's clock. ``error`` is why the session has to fail before it's
    played, and ``records`` is whether it has records not yet queued.
    """

    id: int
    game: object | None
    channel: str | None
    token: str
    renewed: float
    saved: str
    position: str | None
    applied: int
    origin: float
    error: Exception | None = None
    next_pass: float = 0
    records: bool = True


class Runner:
    """Plays the sessions of ``games``, a dict from each channel to its game
    type's instance, until :meth:`stop` is called.

    A runner in the main thread enforces each game type's
    :attr:`~dallinger.realtime.game.RealtimeGame.time_limit`. One in another
    thread can't, because the limit uses a signal.
    """

    def __init__(self, games, name=None):
        self.games = games
        self.name = name or "{}-{}-{}".format(
            socket.gethostname(), os.getpid(), uuid.uuid4().hex[:8]
        )
        self.sessions = {}
        # Claims the runner holds on sessions it isn't playing, by session id:
        # the ones it held when it lost redis, and one it's adding.
        self.held = {}
        self.stopping = threading.Event()
        self.limited = False
        # Redis's clock less this host's, so session times match entry IDs.
        self.offset = 0
        self.next_claim = 0
        # When the runner may claim sessions it doesn't hold. None after it
        # loses redis, until it balances its sessions again.
        self.next_new_claims = 0
        self.next_records = 0
        self.next_slow_log = 0
        self.redis_lost = False
        self.last_heartbeat = 0

    def stop(self):
        """Stop the runner once it has finished what it's doing, which takes
        at most :data:`CLAIM_INTERVAL` seconds while it waits for messages.
        It then plays its sessions one last time, for up to
        :data:`SHUTDOWN_PLAY_TIME` seconds, and gives them up.
        """
        self.stopping.set()

    def run(self):
        """Play sessions until :meth:`stop` is called.

        :raises RuntimeError: if redis is older than 7.0
        """
        store.check_redis()
        self.limited = threading.current_thread() is threading.main_thread()
        logger.info(
            "Runner %s playing %s%s.",
            self.name,
            ", ".join(sorted(self.games)) or "no game types",
            "" if self.limited else ", without time limits",
        )
        while not self.stopping.is_set():
            try:
                self.step()
            except (RedisConnectionError, RedisTimeoutError) as error:
                self.lose_redis(error)
                continue
            if self.redis_lost:
                self.redis_lost = False
                logger.info("Runner %s reached redis again.", self.name)
        self.let_go()

    def let_go(self):
        """Play every session the runner holds one last time, give them up,
        and stop counting as running.
        """
        try:
            self.play_now(list(self.sessions), time.monotonic() + SHUTDOWN_PLAY_TIME)
            # Playing can renew the runner's heartbeat.
            store.remove_runner(self.name)
            store.release_session_claims(
                {
                    **self.held,
                    **{
                        session_id: session.token
                        for session_id, session in self.sessions.items()
                    },
                }
            )
        except (RedisConnectionError, RedisTimeoutError) as error:
            logger.warning(
                "Runner %s couldn't give up its sessions, and other runners "
                "take them over once its claims expire: %s",
                self.name,
                error,
            )
        self.sessions = {}

    def lose_redis(self, error):
        if not self.redis_lost:
            self.redis_lost = True
            logger.warning(
                "Runner %s lost its connection to redis, and stops playing its "
                "sessions until it's back: %s",
                self.name,
                error,
            )
        self.held.update(
            {session_id: session.token for session_id, session in self.sessions.items()}
        )
        self.sessions = {}
        self.next_claim = 0
        self.next_new_claims = None
        self.stopping.wait(REDIS_RETRY_INTERVAL)

    def clock(self):
        return time.time() + self.offset

    def step(self):
        """Wait for entries or the next due session, and play."""
        clock = self.clock()
        if clock >= self.next_claim:
            self.offset = store.server_time() - time.time()
            clock = self.clock()
            self.balance_sessions(clock)
            self.next_claim = clock + CLAIM_INTERVAL
        if clock >= self.next_records:
            self.queue_records()
            self.next_records = clock + RECORDS_INTERVAL
        wake = min(
            [session.next_pass for session in self.sessions.values()]
            + [self.next_claim, self.next_records]
        )
        timeout = wake - self.clock()
        if not self.sessions:
            self.stopping.wait(max(timeout, 0))
            return
        positions = {
            session_id: session.position
            for session_id, session in self.sessions.items()
        }
        self.play(store.read_entries(positions, timeout, MAX_PASS_ENTRIES))

    def balance_sessions(self, clock):
        """Claim the running sessions that belong to this runner, and give up
        the ones that belong to another.
        """
        if self.next_new_claims is None:
            # The other runners lost redis too, and their heartbeats may have
            # expired before they reach it again.
            self.next_new_claims = clock + HEARTBEAT_TTL
        self.resume_sessions(clock)
        runners = self.mark_alive(clock)
        owned = {
            session_id
            for session_id in store.running_sessions()
            if owner(session_id, runners) == self.name
        }
        self.release_sessions([each for each in self.sessions if each not in owned])
        if clock >= self.next_new_claims:
            self.claim_sessions(sorted(owned.difference(self.sessions)), clock)

    def mark_alive(self, clock):
        self.last_heartbeat = clock
        return store.mark_runner_alive(self.name, clock, HEARTBEAT_TTL)

    def resume_sessions(self, clock):
        """Play on the sessions whose claims the runner still holds after
        losing redis, from what redis saved.
        """
        if not self.held:
            return
        lost = store.extend_session_claims(self.held, CLAIM_TTL)
        for session_id, token in list(self.held.items()):
            if session_id in lost:
                logger.warning(
                    "Runner %s lost its claim on session %s.", self.name, session_id
                )
            else:
                handovers = store.count_handovers(session_id, clock - HANDOVER_WINDOW)
                self.add_session(session_id, token, clock, handovers)
            del self.held[session_id]

    def release_sessions(self, session_ids):
        if not session_ids:
            return
        self.play_now(session_ids)
        session_ids = [each for each in session_ids if each in self.sessions]
        store.release_session_claims(
            {session_id: self.sessions[session_id].token for session_id in session_ids}
        )
        for session_id in session_ids:
            del self.sessions[session_id]
        logger.info(
            "Runner %s gave up %d sessions to other runners.",
            self.name,
            len(session_ids),
        )

    def play_now(self, session_ids, deadline=None):
        """Play the sessions with the entries they have, so that what's saved
        is from now, and the runner taking them over goes on from now. No
        pass starts after ``deadline``, a ``time.monotonic()`` time.
        """
        if not session_ids:
            return
        for session_id in session_ids:
            self.sessions[session_id].next_pass = 0
        self.play(
            store.read_entries(
                {
                    session_id: self.sessions[session_id].position
                    for session_id in session_ids
                },
                0,
                MAX_PASS_ENTRIES,
            ),
            deadline,
        )

    def claim_sessions(self, session_ids, clock):
        for session_id in session_ids:
            claimed = store.claim(session_id, self.name, CLAIM_TTL, HANDOVER_WINDOW)
            if claimed is None:
                continue
            token, handovers = claimed
            # Until the session is added, a lost connection to redis keeps
            # the claim with the others the runner resumes.
            self.held[session_id] = token
            self.add_session(session_id, token, clock, handovers)
            del self.held[session_id]

    def add_session(self, session_id, token, clock, handovers):
        error = None
        if handovers >= MAX_HANDOVERS:
            error = RuntimeError(
                "The session changed runners {} times in {} seconds, each "
                "time because the runner playing it stopped without giving "
                "it up.".format(handovers, HANDOVER_WINDOW)
            )
        try:
            loaded = store.load_session(session_id)
        except (KeyError, ValueError) as raised:
            error = RuntimeError(
                "The session's state in redis can't be read: {!r}".format(raised)
            )
            loaded = {"game": None, "saved": "", "position": None, "applied": 0}
        game = self.games.get(loaded["game"])
        if handovers > MAX_HANDOVERS:
            # The runner that failed the session stopped too, so it ends
            # without game code.
            game = None
        self.sessions[session_id] = _Session(
            id=session_id,
            game=game,
            channel=loaded["game"],
            token=token,
            renewed=clock,
            saved=loaded["saved"],
            position=loaded["position"],
            applied=loaded["applied"],
            # The session clock runs only while a runner plays the session.
            origin=clock - session_time(loaded["saved"]),
            error=error,
        )

    def queue_records(self):
        for session_id, session in self.sessions.items():
            if session.records:
                get_queue("default").enqueue(write_records, session_id)
                session.records = False

    def play(self, read, deadline=None):
        """Play the sessions that have new entries or are due, save them, and
        send their views. No pass starts after ``deadline``, a
        ``time.monotonic()`` time.
        """
        started = time.monotonic()
        clock = self.clock()
        lost = store.lost_entries(
            {session_id: self.sessions[session_id].applied for session_id in read}
        )
        passes = []
        timings = []
        for session_id, session in list(self.sessions.items()):
            if deadline is not None and time.monotonic() >= deadline:
                break
            items = read.get(session_id, [])
            if not items and clock < session.next_pass:
                continue
            self.extend_stale_claims()
            if session_id not in self.sessions:
                continue
            began = time.monotonic()
            try:
                result = self.play_session(
                    session, items, lost.get(session_id, 0), clock
                )
            except _BetweenTimeLimits as raised:
                raise raised.error from None
            timings.append((time.monotonic() - began, session))
            applied = [entry_id for entry_id, _ in items]
            passes.append((session_id, session.token, applied, result))
        if not passes:
            return
        saved_at = self.clock()
        lost_claims = store.save_passes(passes, CLAIM_TTL)
        kept = [
            (session_id, applied, result)
            for session_id, _, applied, result in passes
            if session_id not in lost_claims
        ]
        publish_views(
            self.name, [(session_id, result.views) for session_id, _, result in kept]
        )
        for session_id in lost_claims:
            self.drop(session_id)
        for session_id, applied, result in kept:
            self.after_save(self.sessions[session_id], applied, result, saved_at)
        seconds = time.monotonic() - started
        limit = min(_tick_interval(session.game) for _, session in timings)
        if seconds > limit:
            self.log_slow(seconds, limit, timings)

    def extend_stale_claims(self):
        """Extend the claims, and the runner's heartbeat, that a long step
        would otherwise let expire.
        """
        clock = self.clock()
        if clock - self.last_heartbeat > SESSION_RENEW_INTERVAL:
            self.mark_alive(clock)
        stale = {
            session_id: session.token
            for session_id, session in self.sessions.items()
            if clock - session.renewed > SESSION_RENEW_INTERVAL
        }
        if not stale:
            return
        lost = store.extend_session_claims(stale, CLAIM_TTL)
        for session_id in stale:
            if session_id in lost:
                self.drop(session_id)
            else:
                self.sessions[session_id].renewed = clock

    def extend_claims_between_time_limits(self):
        try:
            self.extend_stale_claims()
        except RedisError as error:
            raise _BetweenTimeLimits(error)

    def drop(self, session_id):
        if self.sessions.pop(session_id, None) is not None:
            logger.warning(
                "Runner %s lost its claim on session %s.", self.name, session_id
            )

    def play_session(self, session, items, lost, clock):
        now = clock - session.origin
        game = session.game
        time_limit = game.time_limit if self.limited and game is not None else None
        entries = []
        try:
            entries = [store.read_entry(*item) for item in items]
            for entry in entries:
                entry["time"] = entry["received"] - session.origin
            error = _problem(session, entries, lost, clock)
            if error is None:
                return run_pass(
                    game,
                    session.saved,
                    entries,
                    now,
                    clock,
                    time_limit,
                    self.extend_claims_between_time_limits,
                )
        except Exception as raised:
            error = raised
        return fail_session(
            game,
            session.saved,
            entries,
            now,
            clock,
            error,
            time_limit,
            self.extend_claims_between_time_limits,
        )

    def after_save(self, session, applied, result, saved_at):
        session.renewed = saved_at
        if applied:
            session.position = applied[-1]
            session.applied += len(applied)
        if result.ended is not None:
            if result.ended["reason"] == FAILED:
                logger.error(
                    "Session %s of %s failed:\n%s",
                    session.id,
                    session.channel,
                    result.ended["error"],
                )
            del self.sessions[session.id]
            get_queue("high").enqueue(write_records, session.id)
            return
        session.saved = result.saved
        session.records = session.records or bool(result.records)
        session.next_pass = saved_at + SESSION_RENEW_INTERVAL
        if result.next_due is not None:
            session.next_pass = min(session.next_pass, session.origin + result.next_due)

    def log_slow(self, seconds, limit, timings):
        if self.clock() < self.next_slow_log:
            return
        self.next_slow_log = self.clock() + SLOW_LOG_INTERVAL
        slowest = sorted(timings, key=lambda each: each[0], reverse=True)[:3]
        logger.warning(
            "Runner %s took %.3f seconds to play, save and send %d sessions, "
            "longer than the %.3f second tick interval. The slowest: %s.",
            self.name,
            seconds,
            len(timings),
            limit,
            ", ".join(
                "session {} of {} ({:.3f} seconds)".format(
                    session.id, session.channel, took
                )
                for took, session in slowest
            ),
        )


def _problem(session, entries, lost, clock):
    """Why a session has to fail before it's played, or ``None``."""
    if session.error is not None:
        return session.error
    if session.game is None:
        return RuntimeError(
            "No game type of the experiment has the channel {!r}.".format(
                session.channel
            )
        )
    if lost:
        return RuntimeError(
            "The session's stream dropped {} entries before they were applied, "
            "because it reached {} entries.".format(lost, store.MAX_ENTRIES)
        )
    if entries and clock - entries[0]["received"] > MAX_ENTRY_WAIT:
        return RuntimeError(
            "An entry waited {:.1f} seconds to be applied, more than {}.".format(
                clock - entries[0]["received"], MAX_ENTRY_WAIT
            )
        )
    return None


def owner(session_id, runners):
    """Return which of ``runners``, a list of names, a session belongs to.

    This is rendezvous hashing: when a runner joins or leaves, only the
    sessions that belong to it change hands.
    """
    return max(
        runners,
        key=lambda runner: hashlib.blake2b(
            "{}:{}".format(session_id, runner).encode()
        ).digest(),
    )


def _tick_interval(game):
    if game is None or not game.tick_rate:
        return SLOW
    return 1 / game.tick_rate
