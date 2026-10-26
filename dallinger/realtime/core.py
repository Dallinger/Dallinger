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
- ``join`` and ``leave``: ``participant``, ``scope`` and ``socket``, a string
  naming one socket, different for every socket in the deployment
- ``clock``: a page's clock measurement, with ``participant``, ``scope``,
  ``browser_time``, ``server_time``, ``round_trip`` and ``received``, as
  :mod:`dallinger.realtime.session_sockets` describes. It's recorded, and no
  game code sees it.
- ``end``: ``reason``, a non-empty string

A pass keeps each entry's time between the session's time before the pass and
the pass's own time. A page stays open while any of its sockets is, so a
repeated join or leave, or a leave for a socket that isn't open, changes
nothing.

A pass that raises, game code calling ``sys.exit()`` included, or runs out
of time in game code, fails its session instead. The failed session keeps its
state from before the pass, records the pass's messages with the status
``"failed"``, and ends with the reason :data:`~dallinger.realtime.game.FAILED`.
:func:`fail_session` ends a session the same way, for a problem the runner
finds outside a pass.
"""

import json
import math
import traceback
from dataclasses import dataclass

from dallinger.realtime.game import (
    FAILED,
    FINISHED,
    MAX_DURATION,
    NOT_JOINED,
    Reject,
    Sent,
    queued_effects,
)
from dallinger.realtime.time_limit import TimeLimitExceeded, time_budget
from dallinger.realtime.utils import copy_json, dump_json, is_int

#: How many rounds of bot messages may follow one event in a game without
#: ticks. A pass whose bots are still sending messages after that raises.
MAX_BOT_ROUNDS = 1000

# Envelope numbers are recorded in a Postgres integer column.
_MAX_NUMBER = 2**31 - 1

# What game code or the core can raise that fails a session. The runner's own
# shutdown never raises SystemExit, so one raised here came from game code.
_FAILURES = (Exception, SystemExit, TimeLimitExceeded)


@dataclass
class PassResult:
    """What one pass produced.

    ``saved`` is the session after the pass, as JSON text.

    ``views`` lists a ``{"participant", "scope", "view"}`` dict for each open
    page the pass sent a view to. ``view`` is the view envelope, as
    :mod:`dallinger.realtime.delivery` describes it. Its ``number`` counts
    the passes that sent views, and its ``time`` and ``clock`` are the pass's.

    ``records`` are for Postgres, in order. Each has a ``sequence`` number, a
    ``type`` and a session ``time``, except the end record of a session
    :func:`fail_session` can't read. The types are:

    - ``message``: ``participant``, ``scope``, ``payload``, the envelope's
      ``number``, ``browser_time`` and ``view_time``, the clock time it was
      ``received``, its ``status`` (``"accepted"``, ``"rejected"`` or
      ``"failed"``) and the rejection's ``reason``
    - ``clock``: a clock entry's ``participant``, ``scope``,
      ``browser_time``, ``server_time``, ``round_trip`` and ``received``
    - ``effect``: the ``name`` and ``payload`` game code queued
    - ``checkpoint``: the ``state``
    - ``end``: the ``reason``, ``outcome``, final ``state`` and ``error``

    ``ended`` is the session's ending if this pass ended it, otherwise
    ``None``. It holds the ending's ``time``, ``reason`` and ``outcome``, the
    final ``views`` of the players who aren't bots, and the ``error``: the
    traceback of a failed session, otherwise ``None``.

    ``next_due`` is the session time of the session's next tick, or of the
    time it ends at, from
    :attr:`~dallinger.realtime.RealtimeGame.max_duration` or
    :attr:`~dallinger.realtime.RealtimeGame.join_timeout`, if that comes
    first: the time by which the session needs another pass even if no entry
    arrives. It's ``None`` if neither is coming, or the session has ended.
    """

    saved: str
    views: list
    records: list
    ended: dict | None
    next_due: float | None


def new_session(game, members, bots=()):
    """Return a new saved session of ``game`` for ``members``.

    :param members: the participant ids of the session's players, bots
        included
    :param bots: the players the runner plays for, using
        :meth:`~dallinger.realtime.RealtimeGame.bot`
    """
    members = [str(member) for member in members]
    bots = [str(bot) for bot in bots]
    if not set(bots) <= set(members):
        raise ValueError("Every bot must be a member.")
    return dump_json(
        {
            "state": copy_json(
                game.initial_state(list(members)),
                "{}.initial_state's return value".format(type(game).__name__),
            ),
            "members": members,
            "bots": bots,
            "time": 0,
            "next_tick": 1 / game.tick_rate if game.tick_rate else None,
            "last_tick": None,
            "last_checkpoint": 0,
            "view_number": 0,
            "record_number": 0,
            # Open pages, each with its open sockets, the number of the last
            # message processed from it, and rejections it hasn't been sent.
            "pages": [],
            "bot_messages": {bot: 0 for bot in bots},
            "started": False,
            # Whether a page has opened. Bots have no pages.
            "joined": False,
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
        before the session fails, or ``None`` for no limit. A session that
        fails gets ``outcome`` and its final views from what's left of it.
        The limit uses ``SIGALRM`` and ``ITIMER_REAL`` while the pass runs,
        so it only works in the main thread.
    :returns: a :class:`PassResult`
    """
    with time_budget(time_limit) as budget:
        try:
            return _Pass(game, saved, now, clock, budget).run(entries)
        except _FAILURES as error:
            return _Pass(game, saved, now, clock, budget).fail(entries, error)


def fail_session(
    game,
    saved,
    entries,
    now,
    clock,
    error,
    time_limit=None,
):
    """End the ``saved`` session as failed with ``error``, an exception, for a
    problem found outside a pass, recording ``entries`` as a failing pass does.

    ``game`` is ``None`` when no game type has the session's channel. Then, or
    if the saved session or its entries can't be read, the session ends
    without game code: the ending has no outcome and no final views, and no
    entries are recorded. A saved session that can't be read is kept as it is,
    and its end record's ``sequence`` and ``time`` are ``None``.

    The other arguments are those of :func:`run_pass`.
    """
    if game is not None:
        with time_budget(time_limit) as budget:
            for recorded in (entries, []):
                try:
                    return _Pass(game, saved, now, clock, budget).fail(recorded, error)
                except Exception:
                    pass
    return _bare_failure(saved, error)


def session_time(saved):
    """Return a saved session's time, or 0 if it can't be read."""
    try:
        return json.loads(saved)["time"]
    except (ValueError, KeyError, TypeError):
        return 0


def _bare_failure(saved, error):
    text = "".join(traceback.format_exception(error))
    ended = {
        "time": None,
        "reason": FAILED,
        "outcome": None,
        "views": {},
        "error": text,
    }
    record = {
        "sequence": None,
        "type": "end",
        "time": None,
        "reason": FAILED,
        "outcome": None,
        "state": None,
        "error": text,
    }
    try:
        session = json.loads(saved)
        ended["time"] = record["time"] = session["time"]
        record["sequence"] = session["record_number"] + 1
        record["state"] = session["state"]
    except (ValueError, KeyError, TypeError):
        return PassResult(saved, [], [record], ended, None)
    session["record_number"] = record["sequence"]
    session["ended"] = ended
    return PassResult(dump_json(session), [], [record], ended, None)


def parse_message(data):
    """Return the payload and the :class:`~dallinger.realtime.Sent` of a
    game frame's ``data``.

    Data that isn't JSON, or is nested too deeply to read, is a string
    payload. A frame without an envelope gets
    a ``Sent`` whose values are all ``None``, and an envelope value that's
    missing or invalid is ``None``.
    """
    try:
        value = json.loads(
            data, parse_constant=_refuse_constant, parse_float=_finite_float
        )
    # json.loads raises RecursionError for deeply nested arrays or objects.
    except (ValueError, RecursionError):
        return data, Sent()
    if (
        isinstance(value, dict)
        and value.keys() == {"envelope", "payload"}
        and isinstance(value["envelope"], dict)
    ):
        envelope = value["envelope"]
        number = envelope.get("number")
        return value["payload"], Sent(
            number=number if is_int(number) and 0 <= number <= _MAX_NUMBER else None,
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


def _time(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            return float(value)
        except OverflowError:
            pass
    return None


def _read_message(entry):
    payload, sent = parse_message(entry["data"])
    return entry["participant"], entry["scope"], payload, sent, entry["received"]


def _read_socket(entry):
    return entry["participant"], entry["scope"], entry["socket"]


_CLOCK_FIELDS = (
    "participant",
    "scope",
    "browser_time",
    "server_time",
    "round_trip",
    "received",
)


def _read_clock(entry):
    return {name: entry[name] for name in _CLOCK_FIELDS}


class _Pass:
    def __init__(self, game, saved, now, clock, budget):
        self.game = game
        self.name = type(game).__name__
        # Names the state when the session fails to dump. Everything else in
        # the session is already JSON, so only the state can fail.
        self.state_name = "{}'s state".format(self.name)
        self.saved = saved
        self.session = session = json.loads(saved)
        self.state = session["state"]
        self.time = session["time"]
        self.now = max(now, self.time)
        self.clock = clock
        self.budget = budget
        self.pages = {
            (page["participant"], page["scope"]): page for page in session["pages"]
        }
        self.recipients = set()
        self.records = []
        self.ticked = False
        self.end_reason = None
        self.failed = False

    def run(self, entries):
        session = self.session
        if session["ended"] is not None:
            return PassResult(self.saved, [], [], None, None)
        before = (
            dump_json(self.state, self.state_name) if not self.game.tick_rate else None
        )
        if not session["started"]:
            session["started"] = True
            # A bot has no page, so it joins as the session starts
            for bot in session["bots"]:
                self.record_effects(self.effects_of("on_join", self.state, bot, 0))
            self.check_over()
            if not self.game.tick_rate:
                self.bots_play()
        pending = iter(entries)
        entry = next(pending, None)
        tick_time = None
        while self.end_reason is None:
            entry_time = None if entry is None else self.entry_time(entry)
            tick_time = self.next_tick()
            is_tick = (
                tick_time is not None
                and tick_time <= self.now
                and (entry is None or tick_time < entry_time)
            )
            event_time = tick_time if is_tick else entry_time
            limit, reason = self.time_up()
            if (
                limit is not None
                and (self.now if event_time is None else event_time) >= limit
            ):
                self.time = max(limit, self.time)
                self.end_reason = reason
                break
            if event_time is None:
                break
            self.time = event_time
            if is_tick:
                self.tick()
            else:
                self.handle(entry)
                entry = next(pending, None)

        changed = before is not None and (
            dump_json(self.state, self.state_name) != before
        )
        next_due = None
        if self.end_reason is not None:
            self.end()
        else:
            self.time = self.now
            interval = self.game.checkpoint_interval
            if interval is not None and (
                self.time >= session["last_checkpoint"] + interval
            ):
                self.add_record("checkpoint", state=self.state)
                session["last_checkpoint"] = self.time
            # The loop stopped at a tick still to come, if there is one.
            due = [tick_time, self.time_up()[0]]
            next_due = min((each for each in due if each is not None), default=None)
        return self.finish(
            everyone=self.ticked or changed or self.end_reason is not None,
            next_due=next_due,
        )

    def fail(self, entries, error):
        """End the session at its state from before the pass.

        The pass's messages are recorded as failed, its clock measurements
        are recorded, and its joins and leaves open and close pages, up to
        where the pass would have stopped. No game code runs except
        ``outcome`` and ``view`` for the ending.
        """
        self.failed = True
        for entry in entries:
            self.time = self.entry_time(entry)
            kind = entry["type"]
            limit, _ = self.time_up()
            if kind == "end" or (limit is not None and self.time >= limit):
                break
            if kind == "message":
                participant, scope, payload, sent, received = _read_message(entry)
                record = self.message_record(
                    participant, scope, payload, sent, received, "failed"
                )
                self.add_record("message", **record)
                self.note_processed(participant, scope, sent, record)
            elif kind == "clock":
                self.add_record("clock", **_read_clock(entry))
            elif kind == "join":
                self.open_page(*_read_socket(entry))
            elif kind == "leave":
                self.close_page(*_read_socket(entry))
        self.time = self.now
        self.end_reason = FAILED
        self.end(error="".join(traceback.format_exception(error)))
        return self.finish(everyone=True, next_due=None)

    def entry_time(self, entry):
        return min(max(entry["time"], self.time), self.now)

    def time_up(self):
        """Return the session time the session ends at, if nothing ends it
        first, and the reason, or ``(None, None)``.
        """
        ends = []
        if self.game.max_duration is not None:
            ends.append((self.game.max_duration, MAX_DURATION))
        session = self.session
        if (
            self.game.join_timeout is not None
            and not session["joined"]
            and set(session["members"]) - set(session["bots"])
        ):
            ends.append((self.game.join_timeout, NOT_JOINED))
        return min(ends, default=(None, None))

    def finish(self, everyone, next_due):
        self.session["time"] = self.now
        views = self.page_views(everyone)
        saved = dump_json(self.session, self.state_name)
        copied = copy_json({"records": self.records, "ended": self.session["ended"]})
        return PassResult(saved, views, copied["records"], copied["ended"], next_due)

    def call(self, name, *args, returns=False):
        """Call the game's method ``name`` within the time limit.

        A call that ``returns`` a value the session keeps or sends gets a
        copy of it.
        """
        what = "{}.{}".format(self.name, name)
        result = self.budget.run(what, getattr(self.game, name), *args)
        if returns:
            result = copy_json(result, "{}'s return value".format(what))
        return result

    def effects_of(self, name, *args):
        """Call the game's method ``name`` and return the effects it queued."""
        effects = []
        token = queued_effects.set(effects)
        try:
            self.call(name, *args)
        finally:
            queued_effects.reset(token)
        return effects

    def record_effects(self, effects):
        for name, payload in effects:
            self.add_record("effect", name=name, payload=payload)

    def value_of(self, name, *args):
        """Return a copy of what ``view`` or ``outcome`` returns.

        A failed session gets ``None`` instead of failing again.
        """
        if not self.failed:
            return self.call(name, *args, returns=True)
        try:
            return self.call(name, *args, returns=True)
        except _FAILURES:
            return None

    def add_record(self, type, **fields):
        self.session["record_number"] += 1
        record = {
            "sequence": self.session["record_number"],
            "type": type,
            "time": self.time,
            **fields,
        }
        self.records.append(record)
        return record

    def next_tick(self):
        """The time of the next tick, or ``None``."""
        times = []
        next_tick = self.session["next_tick"]
        if next_tick is not None:
            times.append(next_tick)
        deadline = self.call("next_deadline", self.state)
        last_tick = self.session["last_tick"]
        if deadline is not None and (last_tick is None or deadline > last_tick):
            times.append(max(deadline, self.time))
        return min(times, default=None)

    def tick(self):
        candidate = copy_json(self.state, self.state_name)
        effects = self.effects_of("tick", candidate, self.time)
        self.state = candidate
        self.session["state"] = self.state
        self.record_effects(effects)
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
        if kind == "clock":
            self.add_record("clock", **_read_clock(entry))
            return
        if kind == "message":
            self.apply(*_read_message(entry))
        elif kind == "join":
            self.join(*_read_socket(entry))
        elif kind == "leave":
            self.leave(*_read_socket(entry))
        else:
            raise ValueError("Unknown entry type {!r}.".format(kind))
        if not self.game.tick_rate:
            self.bots_play()

    def apply(self, participant, scope, payload, sent, received):
        record = self.message_record(
            participant, scope, payload, sent, received, "accepted"
        )
        rejection = None
        effects = []
        candidate = copy_json(self.state, self.state_name)
        try:
            effects = self.effects_of(
                "apply", candidate, participant, payload, self.time, sent
            )
        except Reject as raised:
            rejection = raised
            record["status"] = "rejected"
            record["reason"] = copy_json(
                raised.reason, "{}.apply's Reject reason".format(self.name)
            )
        else:
            self.state = candidate
            self.session["state"] = self.state
        keep = self.call(
            "save_message", self.state, participant, record["payload"], rejection
        )
        if keep is not True and keep is not False:
            raise TypeError(
                "{}.save_message returned {!r}, not True or False.".format(
                    self.name, keep
                )
            )
        if keep:
            self.add_record("message", **record)
        self.record_effects(effects)
        self.note_processed(participant, scope, sent, record)
        self.check_over()
        return rejection is None

    def message_record(self, participant, scope, payload, sent, received, status):
        """A message record's fields, before it has a sequence number."""
        return dict(
            participant=participant,
            scope=scope,
            # Copied first, since apply may keep the payload and change it.
            payload=copy_json(payload),
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

    def join(self, participant, scope, socket):
        if self.open_page(participant, scope, socket):
            candidate = copy_json(self.state, self.state_name)
            effects = self.effects_of("on_join", candidate, participant, self.time)
            self.state = candidate
            self.session["state"] = self.state
            self.record_effects(effects)
            self.check_over()

    def leave(self, participant, scope, socket):
        if self.close_page(participant, scope, socket):
            candidate = copy_json(self.state, self.state_name)
            effects = self.effects_of("on_leave", candidate, participant, self.time)
            self.state = candidate
            self.session["state"] = self.state
            self.record_effects(effects)
            self.check_over()

    def open_page(self, participant, scope, socket):
        """Note a socket opening, returning whether it's the participant's
        first open page.
        """
        first = not self.is_open(participant)
        page = self.pages.get((participant, scope))
        if page is None:
            page = {
                "participant": participant,
                "scope": scope,
                "sockets": [],
                "last_processed": None,
                "rejected": [],
            }
            self.pages[participant, scope] = page
            self.session["pages"].append(page)
        if socket not in page["sockets"]:
            page["sockets"].append(socket)
        self.session["joined"] = True
        self.recipients.add((participant, scope))
        return first

    def close_page(self, participant, scope, socket):
        """Note a socket closing, returning whether the participant's last
        open page closed.
        """
        page = self.pages.get((participant, scope))
        if page is None or socket not in page["sockets"]:
            return False
        page["sockets"].remove(socket)
        if page["sockets"]:
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
        self.add_record(
            "end",
            reason=self.end_reason,
            outcome=outcome,
            state=self.state,
            error=error,
        )

    def page_views(self, everyone):
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
                view = copy_json(view)
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
                        "tick_rate": self.game.tick_rate,
                        "last_processed": page["last_processed"],
                        "rejected": page["rejected"],
                        "ended": None if ended is None else ended["reason"],
                        "view": view,
                    },
                }
            )
            page["rejected"] = []
        return views
