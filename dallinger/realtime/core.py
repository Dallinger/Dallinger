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
"""

import json
import math
from dataclasses import dataclass

from dallinger.realtime.game import (
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
      ``received``, its ``status`` (``"accepted"`` or ``"rejected"``) and
      the rejection's ``reason``
    - ``effect``: the ``name`` and ``payload`` game code queued
    - ``checkpoint``: the ``state``
    - ``end``: the ``reason``, ``outcome`` and final ``state``

    ``ended`` is the session's ending if this pass ended it, otherwise
    ``None``. It holds the ending's ``time``, ``reason`` and ``outcome``, and
    the final ``views`` of the players who aren't bots.
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
            "version": game.version,
            "state": game.initial_state(list(members)),
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


def run_pass(game, saved, entries, now, clock):
    """Apply ``entries`` and any ticks due by ``now`` to the ``saved`` session.

    :param saved: a session from :func:`new_session` or an earlier pass
    :param entries: the session's new entries, in the order they arrived
    :param now: the session time of this pass. A time before the saved
        session's counts as the saved session's time.
    :param clock: the runner's clock, in seconds since the epoch
    :returns: a :class:`PassResult`
    """
    return _Pass(game, json.loads(saved), now, clock).run(saved, entries)


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


class _Pass:
    def __init__(self, game, session, now, clock):
        self.game = game
        self.session = session
        self.state = session["state"]
        self.time = session["time"]
        self.now = max(now, self.time)
        self.clock = clock
        self.pages = {
            (page["participant"], page["scope"]): page for page in session["pages"]
        }
        self.recipients = set()
        self.records = []
        self.ticked = False
        self.end_reason = None

    def run(self, saved, entries):
        session = self.session
        if session["ended"] is not None:
            return PassResult(saved, [], [], None)
        before = json.dumps(self.state) if not self.game.tick_rate else None
        if not session["started"]:
            session["started"] = True
            if not self.game.tick_rate:
                self.bots_play()
        pending = iter(entries)
        entry = next(pending, None)
        while self.end_reason is None:
            entry_time = None
            if entry is not None:
                entry_time = min(max(entry["time"], self.time), self.now)
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

        changed = before is not None and json.dumps(self.state) != before
        if self.end_reason is not None:
            self.end()
        else:
            self.time = self.now
            if self.time >= session["next_checkpoint"]:
                self.record("checkpoint", state=self.state)
                session["next_checkpoint"] = self.time + CHECKPOINT_INTERVAL
        session["time"] = self.now
        views = self.views(
            everyone=self.ticked or changed or self.end_reason is not None
        )
        saved = _dump(session)
        result = _round_trip(
            {"views": views, "records": self.records, "ended": session["ended"]}
        )
        return PassResult(saved, result["views"], result["records"], result["ended"])

    def call(self, method, *args, with_effects=False):
        """Call game code. A call ``with_effects`` saves the effects it
        queues, unless it raises.
        """
        if not with_effects:
            return method(*args)
        effects = []
        token = queued_effects.set(effects)
        try:
            result = method(*args)
        finally:
            queued_effects.reset(token)
        for name, payload in effects:
            self.record("effect", name=name, payload=payload)
        return result

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
        deadline = self.call(self.game.next_deadline, self.state)
        last_tick = self.session["last_tick"]
        if (
            deadline is not None
            and deadline <= self.now
            and (last_tick is None or deadline > last_tick)
        ):
            times.append(max(deadline, self.time))
        return min(times, default=None)

    def tick(self):
        self.call(self.game.tick, self.state, self.time, with_effects=True)
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
        record = self.record(
            "message",
            participant=participant,
            scope=scope,
            # Copied first, since apply may keep the payload and change it.
            payload=_round_trip(payload),
            number=sent.number,
            browser_time=sent.browser_time,
            view_time=sent.view_time,
            received=received,
            status="accepted",
            reason=None,
        )
        try:
            self.call(
                self.game.apply,
                self.state,
                participant,
                payload,
                self.time,
                sent,
                with_effects=True,
            )
        except Reject as rejection:
            record["status"] = "rejected"
            record["reason"] = rejection.reason
        page = self.pages.get((participant, scope))
        if page is not None:
            if sent.number is not None:
                page["last_processed"] = sent.number
                if record["status"] == "rejected":
                    page["rejected"].append(
                        {"number": sent.number, "reason": record["reason"]}
                    )
            if self.game.send_views_on_messages or not self.game.tick_rate:
                self.recipients.add((participant, scope))
        self.check_over()
        return record["status"] == "accepted"

    def join(self, participant, scope):
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
        if first:
            self.call(
                self.game.on_join, self.state, participant, self.time, with_effects=True
            )
            self.check_over()

    def leave(self, participant, scope):
        page = self.pages.get((participant, scope))
        if page is None:
            return
        page["sockets"] -= 1
        if page["sockets"] > 0:
            return
        del self.pages[participant, scope]
        self.session["pages"].remove(page)
        if not self.is_open(participant):
            self.call(
                self.game.on_leave,
                self.state,
                participant,
                self.time,
                with_effects=True,
            )
            self.check_over()

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
                type(self.game).__name__, MAX_BOT_ROUNDS
            )
        )

    def bot_round(self):
        """Give each bot one move, returning whether any move was accepted."""
        accepted = False
        for bot in self.session["bots"]:
            if self.end_reason is not None:
                break
            view = _round_trip(self.call(self.game.view, self.state, bot))
            message = self.call(self.game.bot, view, bot, self.time)
            if message is None:
                continue
            self.session["bot_messages"][bot] += 1
            sent = Sent(
                number=self.session["bot_messages"][bot],
                browser_time=self.clock,
                view_time=self.time,
            )
            if self.apply(bot, None, _round_trip(message), sent, self.clock):
                accepted = True
        return accepted

    def check_over(self):
        if self.end_reason is None and self.call(self.game.is_over, self.state):
            self.end_reason = FINISHED

    def end(self):
        outcome = self.call(self.game.outcome, self.state, self.end_reason)
        bots = set(self.session["bots"])
        self.session["ended"] = {
            "time": self.time,
            "reason": self.end_reason,
            "outcome": outcome,
            "views": {
                member: self.call(self.game.view, self.state, member)
                for member in self.session["members"]
                if member not in bots
            },
        }
        self.record("end", reason=self.end_reason, outcome=outcome, state=self.state)

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
        player_views = ended["views"] if ended is not None else {}
        views = []
        for page in pages:
            participant = page["participant"]
            if participant not in player_views:
                player_views[participant] = self.call(
                    self.game.view, self.state, participant
                )
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
                        "view": player_views[participant],
                    },
                }
            )
            page["rejected"] = []
        return views
