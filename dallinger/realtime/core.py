"""The session core of the real-time engine.

The runner plays each session in passes, and game code never calls this
module. :func:`run_pass` plays one pass: it applies the session's new entries
and the ticks that are due in time order, and returns the new saved session
with the views, records and ending the pass produced. A saved session is JSON
text holding everything the next pass needs, so a runner that resumes from any
saved session plays the rest of the game the same way.

Entries are dicts, each with a ``type`` and a ``time`` on the session clock:

- ``message``: ``participant``, ``scope``, ``data`` (the frame's text after
  the channel prefix) and ``received`` (the server clock when it arrived)
- ``join`` and ``leave``: ``participant`` and ``scope``, for one socket
- ``end``: ``reason``, a non-empty string

A pass keeps each entry's time between the session's time before the pass and
the pass's own time.

A pass that raises, or runs out of time in game code, fails its session
instead. The failed session keeps its state from before the pass, records the
pass's messages with the status ``"failed"``, and ends with the reason
:data:`~dallinger.realtime.game.FAILED`.
"""

import json
import logging
import math
import os
import signal
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass

from dallinger.realtime.game import (
    FAILED,
    FINISHED,
    MAX_DURATION,
    Reject,
    Sent,
    queued_effects,
)

#: Seconds on the session clock between checkpoints of the state.
CHECKPOINT_INTERVAL = 5

#: How many rounds of bot messages may follow one event in a game without
#: ticks. A pass whose bots are still sending messages after that raises.
MAX_BOT_ROUNDS = 1000

# Envelope numbers are recorded in a Postgres integer column.
_MAX_NUMBER = 2**31 - 1


@dataclass
class PassResult:
    """What one pass produced.

    ``saved`` is the session after the pass, as JSON text.

    ``views`` lists a ``{"participant", "scope", "view"}`` dict for each open
    page the pass sent a view to. ``view`` is the view envelope:

    - ``kind``: ``"tick"`` if the pass ran a tick, otherwise ``"message"``
    - ``number``: counts the passes that sent views
    - ``time`` and ``clock``: the pass's session time and runner clock
    - ``last_processed``: the number of the page's last processed message
    - ``rejected``: a ``{"number", "reason"}`` dict for each of the page's
      messages rejected since its last view
    - ``ended``: the ending's reason, or ``None``
    - ``view``: the player's view of the state

    ``records`` are for Postgres, in order. Each has a ``sequence`` number, a
    ``type`` and a session ``time``. The types are:

    - ``message``: ``participant``, ``scope``, ``payload``, the envelope's
      ``number``, ``browser_time`` and ``view_time``, the clock time it was
      ``received``, its ``status`` (``"accepted"``, ``"rejected"`` or
      ``"failed"``) and the rejection's ``reason``
    - ``effect``: the ``name`` and ``payload`` game code queued
    - ``checkpoint``: the ``state``
    - ``end``: the ``reason``, ``outcome``, final ``state`` and ``error``

    ``ended`` is the session's ending if this pass ended it, otherwise
    ``None``. It holds the ending's ``time``, ``reason`` and ``outcome``, the
    final ``views`` of the players who aren't bots, and the ``error``: the
    traceback of a failed session, otherwise ``None``.
    """

    saved: str
    views: list
    records: list
    ended: dict | None


def new_session(game, members, bots=()):
    """Return a new saved session of ``game`` for ``members``.

    :param members: the participant ids of the session's players, bots
        included
    :param bots: the players the runner plays for, using
        :meth:`~dallinger.realtime.game.RealtimeGame.bot`
    """
    members = [str(member) for member in members]
    bots = [str(bot) for bot in bots]
    if not set(bots) <= set(members):
        raise ValueError("Every bot must be a member.")
    return _dump(
        {
            "state_version": game.state_version,
            "state": _copy(
                game.initial_state(list(members)),
                "{}.initial_state's return value".format(type(game).__name__),
            ),
            "members": members,
            "bots": bots,
            "time": 0,
            "next_tick": 1 / game.tick_rate if game.tick_rate else None,
            "last_tick": None,
            "next_checkpoint": CHECKPOINT_INTERVAL,
            "view_number": 0,
            "record_number": 0,
            # Open pages, each with its socket count, the number of the last
            # message processed from it, and rejections it hasn't been sent.
            "pages": [],
            "bot_messages": {bot: 0 for bot in bots},
            "started": False,
            "ended": None,
        }
    )


def run_pass(game, saved, entries, now, clock, time_limit=None):
    """Apply ``entries`` and any ticks due by ``now`` to the ``saved`` session.

    :param saved: a session from :func:`new_session` or an earlier pass
    :param entries: the session's new entries, in the order they arrived
    :param now: the session time of this pass. A time before the saved
        session's counts as the saved session's time.
    :param clock: the runner's clock, in seconds since the epoch
    :param time_limit: seconds the game's methods may run for in total
        before the session fails, or ``None`` for no limit. The limit uses
        ``SIGALRM`` and ``ITIMER_REAL`` while the pass runs, so it only works
        in the main thread.
    :returns: a :class:`PassResult`
    """
    with _time_limits(time_limit) as new_guard:
        played = _Pass(game, saved, now, clock, new_guard)
        try:
            return played.run(entries)
        except (Exception, TimeLimitExceeded) as error:
            failed = _Pass(game, saved, now, clock, new_guard)
            return failed.fail(entries, error, migrate=not played.migrating)


class TimeLimitExceeded(BaseException):
    """Raised in game code that runs past the session's time limit.

    It isn't an :class:`Exception`, so game code that catches every
    ``Exception`` doesn't catch it.
    """


logger = logging.getLogger(__name__)

#: How long the timer keeps raising in game code that catches its exception
#: and carries on, as a multiple of the time limit, before it ends the process.
#: Only a loop that catches every exception gets that far, and nothing in the
#: process can stop it.
GIVE_UP_AFTER = 2

# While game code runs past its limit, the timer raises again at this interval.
_REPEAT = 0.05

# While a time limit is running: the message to raise, and the clock time to
# give up at.
_running = None


@contextmanager
def _time_limits(seconds):
    """Yield a function that makes a guard for one time budget."""
    if seconds is None:
        yield lambda: _call
        return
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("A time limit only works in the main thread.")
    previous = signal.signal(signal.SIGALRM, _time_out)
    try:
        yield lambda: _TimeLimit(seconds)
    finally:
        signal.signal(signal.SIGALRM, previous)


class _TimeLimit:
    """Calls the game's methods, giving them ``seconds`` in total."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.remaining = seconds

    def __call__(self, what, method, *args):
        global _running
        message = "{} was running when the session used up its {} seconds.".format(
            what, self.seconds
        )
        if self.remaining <= 0:
            raise TimeLimitExceeded(message)
        started = time.monotonic()
        give_up = started + self.remaining + (GIVE_UP_AFTER - 1) * self.seconds
        _running = (message, give_up)
        signal.setitimer(signal.ITIMER_REAL, self.remaining, _REPEAT)
        try:
            result = method(*args)
        finally:
            _stop_timer()
            self.remaining -= time.monotonic() - started
        return result


def _stop_timer():
    global _running
    while True:
        # A signal that arrives before the timer stops raises in here.
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
            _running = None
            return
        except TimeLimitExceeded:
            pass


def _time_out(signum, frame):
    if _running is None:
        return
    message, give_up = _running
    if time.monotonic() >= give_up:
        logger.critical(
            "%s It caught every exception, so the runner is exiting.", message
        )
        os._exit(1)
    raise TimeLimitExceeded(message)


def _call(what, method, *args):
    return method(*args)


def parse_message(data):
    """Return the payload and the :class:`~dallinger.realtime.game.Sent` of a
    game frame's ``data``.

    Data that isn't JSON is a string payload. A frame without an envelope gets
    a ``Sent`` whose values are all ``None``, and an envelope value that's
    missing or invalid is ``None``.
    """
    try:
        value = json.loads(
            data, parse_constant=_refuse_constant, parse_float=_finite_float
        )
    except ValueError:
        return data, Sent()
    if (
        isinstance(value, dict)
        and value.keys() == {"envelope", "payload"}
        and isinstance(value["envelope"], dict)
    ):
        envelope = value["envelope"]
        number = envelope.get("number")
        return value["payload"], Sent(
            number=number if _is_int(number) and 0 <= number <= _MAX_NUMBER else None,
            browser_time=_time(envelope.get("browser_time")),
            view_time=_time(envelope.get("view_time")),
        )
    return value, Sent()


def _refuse_constant(name):
    # NaN and Infinity aren't JSON, and a state holding one couldn't be saved.
    raise ValueError(name)


def _finite_float(text):
    # json.loads reads a number too large for a float, like 1e999, as infinity.
    value = float(text)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _time(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return float(value)
        except OverflowError:
            pass
    return None


def _dump(value):
    return json.dumps(value, allow_nan=False)


def _round_trip(value):
    return json.loads(_dump(value))


def _copy(value, what):
    """Round-trip a value game code handed over, naming it if it isn't JSON."""
    try:
        return _round_trip(value)
    except (TypeError, ValueError) as error:
        raise ValueError("{} isn't JSON: {}".format(what, error)) from error


class _Pass:
    def __init__(self, game, saved, now, clock, new_guard):
        self.game = game
        self.name = type(game).__name__
        self.saved = saved
        self.session = session = json.loads(saved)
        self.state = session["state"]
        self.time = session["time"]
        self.now = max(now, self.time)
        self.clock = clock
        self.new_guard = new_guard
        self.guard = new_guard()
        self.pages = {
            (page["participant"], page["scope"]): page for page in session["pages"]
        }
        self.recipients = set()
        self.records = []
        self.ticked = False
        self.end_reason = None
        self.failed = False
        self.migrating = False

    def run(self, entries):
        session = self.session
        if session["ended"] is not None:
            return PassResult(self.saved, [], [], None)
        before = self.dump(self.state) if not self.game.tick_rate else None
        if session["state_version"] != self.game.state_version:
            self.migrating = True
            self.migrate()
            self.migrating = False
        if not session["started"]:
            session["started"] = True
            if not self.game.tick_rate:
                self.bots_play()
        pending = iter(entries)
        entry = next(pending, None)
        while self.end_reason is None:
            entry_time = None if entry is None else self.entry_time(entry)
            tick_time = self.due_tick()
            is_tick = tick_time is not None and (
                entry is None or tick_time < entry_time
            )
            event_time = tick_time if is_tick else entry_time
            limit = self.game.max_duration
            if (
                limit is not None
                and (self.now if event_time is None else event_time) >= limit
            ):
                self.time = max(limit, self.time)
                self.end_reason = MAX_DURATION
                break
            if event_time is None:
                break
            self.time = event_time
            if is_tick:
                self.tick()
            else:
                self.handle(entry)
                entry = next(pending, None)

        changed = before is not None and self.dump(self.state) != before
        if self.end_reason is not None:
            self.end()
        else:
            self.time = self.now
            if self.time >= session["next_checkpoint"]:
                self.record("checkpoint", state=self.state)
                session["next_checkpoint"] = self.time + CHECKPOINT_INTERVAL
        return self.result(
            everyone=self.ticked or changed or self.end_reason is not None
        )

    def fail(self, entries, error, migrate):
        """End the session at its state from before the pass.

        The pass's messages are recorded as failed and its joins and leaves
        open and close pages, up to where the pass would have stopped. No game
        code runs except ``migrate_state``, unless it's what failed, and
        ``outcome`` and ``view`` for the ending.
        """
        self.failed = True
        if migrate and self.session["state_version"] != self.game.state_version:
            try:
                self.migrate()
            except (Exception, TimeLimitExceeded):
                pass
        limit = self.game.max_duration
        for entry in entries:
            self.time = self.entry_time(entry)
            kind = entry["type"]
            if kind == "end" or (limit is not None and self.time >= limit):
                break
            if kind == "message":
                payload, sent = parse_message(entry["data"])
                participant, scope = entry["participant"], entry["scope"]
                record = self.record_message(
                    participant, scope, payload, sent, entry["received"], "failed"
                )
                self.note_processed(participant, scope, sent, record)
            elif kind == "join":
                self.open_page(entry["participant"], entry["scope"])
            elif kind == "leave":
                self.close_page(entry["participant"], entry["scope"])
        self.time = self.now
        self.end_reason = FAILED
        self.end(error="".join(traceback.format_exception(error)))
        return self.result(everyone=True)

    def migrate(self):
        session = self.session
        self.state = session["state"] = self.call(
            "migrate_state", self.state, session["state_version"], returns=True
        )
        session["state_version"] = self.game.state_version

    def entry_time(self, entry):
        return min(max(entry["time"], self.time), self.now)

    def result(self, everyone):
        self.session["time"] = self.now
        views = self.views(everyone)
        saved = self.dump(self.session)
        result = _round_trip({"records": self.records, "ended": self.session["ended"]})
        return PassResult(saved, views, result["records"], result["ended"])

    def dump(self, value):
        """Dump the state, or the session holding it. Everything else in the
        session is already JSON, so only the state can fail.
        """
        try:
            return _dump(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "{}'s state isn't JSON: {}".format(self.name, error)
            ) from error

    def call(self, name, *args, with_effects=False, returns=False):
        """Call the game's method ``name`` through the guard.

        A call ``with_effects`` saves the effects it queues, unless it raises.
        A call that ``returns`` a value the session keeps or sends gets a
        copy of it.
        """
        what = "{}.{}".format(self.name, name)
        method = getattr(self.game, name)
        if with_effects:
            effects = []
            token = queued_effects.set(effects)
            try:
                result = self.guard(what, method, *args)
            finally:
                queued_effects.reset(token)
            for effect, payload in effects:
                self.record("effect", name=effect, payload=payload)
        else:
            result = self.guard(what, method, *args)
        if returns:
            result = _copy(result, "{}'s return value".format(what))
        return result

    def value_of(self, name, *args):
        """Return a copy of what ``view`` or ``outcome`` returns.

        A failed session gets ``None`` instead of failing again, and never
        calls game code with state from another version.
        """
        if not self.failed:
            return self.call(name, *args, returns=True)
        if self.session["state_version"] != self.game.state_version:
            return None
        try:
            return self.call(name, *args, returns=True)
        except (Exception, TimeLimitExceeded):
            return None

    def record(self, type, **fields):
        self.session["record_number"] += 1
        record = {
            "sequence": self.session["record_number"],
            "type": type,
            "time": self.time,
            **fields,
        }
        self.records.append(record)
        return record

    def due_tick(self):
        """The time of the next tick due by now, or ``None``."""
        times = []
        next_tick = self.session["next_tick"]
        if next_tick is not None and next_tick <= self.now:
            times.append(next_tick)
        deadline = self.call("next_deadline", self.state)
        last_tick = self.session["last_tick"]
        if (
            deadline is not None
            and deadline <= self.now
            and (last_tick is None or deadline > last_tick)
        ):
            times.append(max(deadline, self.time))
        return min(times, default=None)

    def tick(self):
        self.call("tick", self.state, self.time, with_effects=True)
        self.ticked = True
        self.session["last_tick"] = self.time
        next_tick = self.session["next_tick"]
        if next_tick is not None and next_tick <= self.time:
            self.session["next_tick"] = next_tick + 1 / self.game.tick_rate
        self.check_over()
        self.bots_play()

    def handle(self, entry):
        kind = entry["type"]
        if kind == "end":
            reason = entry["reason"]
            if not isinstance(reason, str) or not reason:
                raise ValueError("An end entry's reason must be a non-empty string.")
            self.end_reason = reason
            return
        if kind == "message":
            payload, sent = parse_message(entry["data"])
            self.apply(
                entry["participant"], entry["scope"], payload, sent, entry["received"]
            )
        elif kind == "join":
            self.join(entry["participant"], entry["scope"])
        elif kind == "leave":
            self.leave(entry["participant"], entry["scope"])
        else:
            raise ValueError("Unknown entry type {!r}.".format(kind))
        if not self.game.tick_rate:
            self.bots_play()

    def apply(self, participant, scope, payload, sent, received):
        record = self.record_message(
            participant, scope, payload, sent, received, "accepted"
        )
        try:
            self.call(
                "apply",
                self.state,
                participant,
                payload,
                self.time,
                sent,
                with_effects=True,
            )
        except Reject as rejection:
            record["status"] = "rejected"
            record["reason"] = _copy(
                rejection.reason, "{}.apply's Reject reason".format(self.name)
            )
        self.note_processed(participant, scope, sent, record)
        self.check_over()
        return record["status"] == "accepted"

    def record_message(self, participant, scope, payload, sent, received, status):
        return self.record(
            "message",
            participant=participant,
            scope=scope,
            # Copied first, since apply may keep the payload and change it.
            payload=_round_trip(payload),
            number=sent.number,
            browser_time=sent.browser_time,
            view_time=sent.view_time,
            received=received,
            status=status,
            reason=None,
        )

    def note_processed(self, participant, scope, sent, record):
        """Note a message's number, and any rejection, on the page it came
        from.
        """
        page = self.pages.get((participant, scope))
        if page is None:
            return
        if sent.number is not None:
            page["last_processed"] = sent.number
            if record["status"] == "rejected":
                page["rejected"].append(
                    {"number": sent.number, "reason": record["reason"]}
                )
        if self.game.send_views_on_messages or not self.game.tick_rate:
            self.recipients.add((participant, scope))

    def join(self, participant, scope):
        if self.open_page(participant, scope):
            self.call("on_join", self.state, participant, self.time, with_effects=True)
            self.check_over()

    def leave(self, participant, scope):
        if self.close_page(participant, scope):
            self.call(
                "on_leave",
                self.state,
                participant,
                self.time,
                with_effects=True,
            )
            self.check_over()

    def open_page(self, participant, scope):
        """Count a socket opening, returning whether it's the participant's
        first open page.
        """
        first = not self.is_open(participant)
        page = self.pages.get((participant, scope))
        if page is None:
            page = {
                "participant": participant,
                "scope": scope,
                "sockets": 0,
                "last_processed": None,
                "rejected": [],
            }
            self.pages[participant, scope] = page
            self.session["pages"].append(page)
        page["sockets"] += 1
        self.recipients.add((participant, scope))
        return first

    def close_page(self, participant, scope):
        """Count a socket closing, returning whether the participant's last
        open page closed.
        """
        page = self.pages.get((participant, scope))
        if page is None:
            return False
        page["sockets"] -= 1
        if page["sockets"] > 0:
            return False
        del self.pages[participant, scope]
        self.session["pages"].remove(page)
        return not self.is_open(participant)

    def is_open(self, participant):
        return any(page["participant"] == participant for page in self.pages.values())

    def bots_play(self):
        """Let the bots answer an event.

        With ticks, each bot moves at most once per tick. Without them, bots
        also answer each other's moves, in rounds, until no bot's move is
        accepted.
        """
        if self.game.tick_rate:
            self.bot_round()
            return
        for _ in range(MAX_BOT_ROUNDS):
            if not self.bot_round():
                return
        raise RuntimeError(
            "{}'s bots were still moving after {} rounds.".format(
                self.name, MAX_BOT_ROUNDS
            )
        )

    def bot_round(self):
        """Give each bot one move, returning whether any move was accepted."""
        accepted = False
        for bot in self.session["bots"]:
            if self.end_reason is not None:
                break
            view = self.call("view", self.state, bot, returns=True)
            message = self.call("bot", view, bot, self.time, returns=True)
            if message is None:
                continue
            self.session["bot_messages"][bot] += 1
            sent = Sent(
                number=self.session["bot_messages"][bot],
                browser_time=self.clock,
                view_time=self.time,
            )
            if self.apply(bot, None, message, sent, self.clock):
                accepted = True
        return accepted

    def check_over(self):
        if self.end_reason is None and self.call("is_over", self.state):
            self.end_reason = FINISHED

    def end(self, error=None):
        outcome = self.value_of("outcome", self.state, self.end_reason)
        if self.failed:
            # A slow outcome doesn't cost the players their final views.
            self.guard = self.new_guard()
        bots = set(self.session["bots"])
        self.session["ended"] = {
            "time": self.time,
            "reason": self.end_reason,
            "outcome": outcome,
            "views": {
                member: self.value_of("view", self.state, member)
                for member in self.session["members"]
                if member not in bots
            },
            "error": error,
        }
        self.record(
            "end",
            reason=self.end_reason,
            outcome=outcome,
            state=self.state,
            error=error,
        )

    def views(self, everyone):
        session = self.session
        pages = [
            page
            for page in session["pages"]
            if everyone or (page["participant"], page["scope"]) in self.recipients
        ]
        if not pages:
            return []
        session["view_number"] += 1
        ended = session["ended"]
        player_views = dict(ended["views"]) if ended is not None else {}
        views = []
        shown = set()
        for page in pages:
            participant = page["participant"]
            if participant not in player_views:
                player_views[participant] = self.value_of(
                    "view", self.state, participant
                )
            view = player_views[participant]
            if participant in shown:
                view = _round_trip(view)
            shown.add(participant)
            views.append(
                {
                    "participant": participant,
                    "scope": page["scope"],
                    "view": {
                        "kind": "tick" if self.ticked else "message",
                        "number": session["view_number"],
                        "time": self.now,
                        "clock": self.clock,
                        "last_processed": page["last_processed"],
                        "rejected": page["rejected"],
                        "ended": None if ended is None else ended["reason"],
                        "view": view,
                    },
                }
            )
            page["rejected"] = []
        return views
