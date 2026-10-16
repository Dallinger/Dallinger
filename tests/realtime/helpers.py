"""Game types, entry builders and store readers for the real-time tests."""

import json

from dallinger.realtime import RealtimeGame, Reject, store
from dallinger.realtime.core import new_session, run_pass
from dallinger.realtime.game import FAILED

CLOCK = 1000.0

#: Far more calls to a game's ``next_deadline`` than any test makes. The
#: session core calls it on every turn of its event loop, so a pass whose
#: ticks never stop coming due fails its session here, rather than hanging the
#: test or running the machine out of memory.
MAX_DEADLINE_CHECKS = 2500

#: Each guard hit, so a test whose assertions accept a failed session still
#: fails when the guard is what failed it.
runaway_passes = []


class Tally(RealtimeGame):
    """Logs every call, so a test can read the order things happened in."""

    channel = "tally"
    tick_rate = 4

    def initial_state(self, players):
        return {"players": players, "log": []}

    def apply(self, state, player_id, message, now, sent):
        if message in ("effect", "effect and reject"):
            self.queue_effect("scored", {"by": player_id})
        if message in ("bad", "effect and reject"):
            raise Reject({"code": message})
        state["log"].append([player_id, message, now])

    def tick(self, state, now):
        state["log"].append(["tick", now])

    def next_deadline(self, state):
        self.deadline_checks = getattr(self, "deadline_checks", 0) + 1
        if self.deadline_checks > MAX_DEADLINE_CHECKS:
            message = "next_deadline ran more than {} times.".format(
                MAX_DEADLINE_CHECKS
            )
            runaway_passes.append(message)
            raise RuntimeError(message)
        return state.get("deadline")

    def view(self, state, player_id):
        return {"for": player_id, "log": state["log"]}

    def is_over(self, state):
        return any(entry[1] == "stop" for entry in state["log"])

    def outcome(self, state, reason):
        return {"reason": reason, "moves": len(state["log"])}

    def on_join(self, state, player_id, now):
        state["log"].append(["join", player_id, now])

    def on_leave(self, state, player_id, now):
        state["log"].append(["leave", player_id, now])


class TurnTally(Tally):
    tick_rate = 0


def message(time, participant, payload, number=None, scope="page"):
    if number is None:
        data = json.dumps(payload)
    else:
        envelope = {"number": number, "browser_time": 50.0, "view_time": 0.0}
        data = json.dumps({"envelope": envelope, "payload": payload})
    return {
        "type": "message",
        "time": time,
        "participant": participant,
        "scope": scope,
        "data": data,
        "received": 100.0 + time,
    }


def join(time, participant, scope="page", socket=None):
    return socket_entry("join", time, participant, scope, socket)


def leave(time, participant, scope="page", socket=None):
    return socket_entry("leave", time, participant, scope, socket)


def socket_entry(kind, time, participant, scope, socket):
    """A join or leave, by default for one socket per page."""
    return {
        "type": kind,
        "time": time,
        "participant": participant,
        "scope": scope,
        "socket": "{}/{}".format(participant, scope) if socket is None else socket,
    }


def add(session_id, entry):
    """Add an entry to the session's stream, as a socket would."""
    store.add_entry(
        session_id,
        {key: value for key, value in entry.items() if key not in ("time", "received")},
    )


def handovers(session_id):
    return int(store.redis_conn.get(store.session_key(session_id, "handovers")) or 0)


def started(game, members=("1", "2"), bots=()):
    """A saved session with a page open for each human member."""
    saved = new_session(game, members, bots)
    joins = [join(0, member) for member in members if member not in bots]
    return run_pass(game, saved, joins, 0, CLOCK).saved


def play(game, saved, entries, now):
    return run_pass(game, saved, entries, now, CLOCK)


def session(result):
    return json.loads(result.saved)


def log(result):
    return session(result)["state"]["log"]


def with_deadline(saved, deadline):
    loaded = json.loads(saved)
    loaded["state"]["deadline"] = deadline
    return json.dumps(loaded)


def error(result):
    """The error a pass failed its session with."""
    assert result.ended["reason"] == FAILED
    return result.ended["error"]


def views_by_page(result):
    return {(each["participant"], each["scope"]): each["view"] for each in result.views}


class Restless(TurnTally):
    """Moves once at each session time it's asked at."""

    def bot(self, view, player_id, now):
        if [player_id, "move", now] not in view["log"]:
            return "move"
        return None
