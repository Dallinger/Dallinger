"""Two players play the coins demo over real websockets, through every part of
the real-time engine: a web process, the runner a worker starts beside it, the
worker's jobs that write the record, and Postgres.

It's slow, so it runs only with ``--runslow``, and needs redis and Postgres.
"""

import threading
from pathlib import Path

import pytest
import requests

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession

from .live_server import (
    connect,
    demo_server,
    frames,
    game_message,
    sign_up,
    wait_for,
    wait_for_session,
)

COINS = Path(__file__).parent.parent / "dlgr" / "demos" / "coins"

#: Seconds each player has to collect a coin.
PLAY_SECONDS = 45


@pytest.fixture
def coins_server(tmp_path):
    with demo_server(COINS, tmp_path) as port:
        yield port


def steer(view):
    """A move toward the nearest coin, or ``None`` if there are none."""
    me = view["players"][view["me"]]
    if not view["coins"]:
        return None
    coin = min(
        view["coins"], key=lambda c: (c["x"] - me["x"]) ** 2 + (c["y"] - me["y"]) ** 2
    )

    def direction(gap):
        return 0 if abs(gap) < 0.3 else (1 if gap > 0 else -1)

    dx, dy = direction(coin["x"] - me["x"]), direction(coin["y"] - me["y"])
    if dx == dy == 0:
        return None
    return {"dx": dx, "dy": dy, "seconds": 0.05}


def play(port, participant_id, out):
    """Wait for the session as ``waitForRealtimeSession`` does, join it as
    ``joinRealtimeSession`` does, and chase coins until the result is saved,
    noting what happened in ``out``."""
    try:
        out["session"] = wait_for_session(port, participant_id, "coins")
        ws = connect(
            port,
            "participant_id={}&scope=page&session={}".format(
                participant_id, out["session"]
            ),
        )
        number = 0
        for _, payload in frames(ws, timeout=0.05):
            if payload is not None and payload.get("type") == "realtime_view":
                envelope = payload["view"]
                out["view"] = envelope["view"]
                out["acknowledged"] = envelope["last_processed"]
            elif payload is not None and payload.get("type") == "realtime_saved":
                out["saved"] = payload
                break
            move = "view" in out and steer(out["view"])
            if move:
                ws.send(game_message("coins", number, move))
                number += 1
        ws.close()
    except Exception as error:
        out["error"] = repr(error)


def coins_of(out, participant_id):
    view = out.get("view")
    return view["players"][str(participant_id)]["coins"] if view else 0


@pytest.mark.slow
def test_two_players_play_a_session_to_its_saved_outcome(coins_server):
    from dallinger.realtime import store

    base = "http://127.0.0.1:{}".format(coins_server)
    requests.post(base + "/launch").raise_for_status()
    # The second player's node fills the group, which starts the session
    players = [sign_up(base, number) for number in (1, 2)]
    outs = {player: {} for player in players}
    threads = [
        threading.Thread(target=play, args=(coins_server, player, outs[player]))
        for player in players
    ]
    for thread in threads:
        thread.start()

    wait_for(
        lambda: (
            all(coins_of(outs[p], p) for p in players)
            or any("error" in o for o in outs.values())
        ),
        PLAY_SECONDS,
        "both players to collect a coin",
    )
    assert not [o["error"] for o in outs.values() if "error" in o]
    session_id = outs[players[0]]["session"]
    store.end_realtime_session(session_id, "stopped")
    for thread in threads:
        thread.join(30)

    for player in players:
        out = outs[player]
        assert out["session"] == session_id
        # The game acknowledged the page's moves, and saved its result
        assert out.get("acknowledged") is not None
        assert out.get("saved", {}).get("status") == "ended", "no saved result"

    db.session.remove()
    row = db.session.get(RealtimeSession, session_id)
    assert row.status == "ended"
    assert row.end_reason == "stopped"
    final = row.outcome["coins"]
    assert all(final[str(player)] >= 1 for player in players)
    events = db.session.query(RealtimeEvent).filter_by(session_id=session_id)
    for player in players:
        assert events.filter_by(event_type="message", participant_id=player).count()
    assert events.filter_by(event_type="end").count() == 1
