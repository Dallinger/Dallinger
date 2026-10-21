"""Two players play two rounds of the bargaining demo, with chat, over real
websockets: a web process, the runner a worker starts beside it, the effect
that starts the second round, the experiment's chat relay, and Postgres.

It's slow, so it runs only with ``--runslow``, and needs redis and Postgres.
"""

import json
import threading
from pathlib import Path

import pytest
import requests

from dallinger import db
from dallinger.models import Info, RealtimeSession

from .live_server import (
    connect,
    demo_server,
    frames,
    game_message,
    sign_up,
    wait_for_session,
)

BARGAINING = Path(__file__).parent.parent / "dlgr" / "demos" / "bargaining"

#: A round with no possible deal ends when its clock runs out, so it's short.
SETTINGS = {"rounds": "2", "chat": "true", "bargaining_seconds": "3"}

GREETING = "hello"


@pytest.fixture
def bargaining_server(tmp_path):
    with demo_server(BARGAINING, tmp_path, SETTINGS) as port:
        yield port


def bargain(view, accepted):
    """The seller offers their cost, and the buyer accepts it if it's no more
    than their value; otherwise the clock runs out. Returns a move or
    ``None``."""
    if view["deal"] is not None:
        return None
    if view["role"] == "seller":
        return None if view["my_offer"] is not None else {"offer": view["value"]}
    offer = view["their_offer"]
    if offer is not None and offer <= view["value"] and not accepted:
        return {"accept": offer}
    return None


def play(port, participant_id, greets, out):
    """Play every round as the page does with chat on: wait for each round,
    join it on ``/chat``, and wait for the next once it's saved. In the first
    round the player waits to hear the greeting before bargaining, and sends
    it if ``greets``."""
    out["rounds"], out["chat"] = [], []
    after = None
    try:
        for _ in range(2):
            session = wait_for_session(port, participant_id, "bargain", after)
            ws = connect(
                port,
                "participant_id={}&scope=page&session={}".format(
                    participant_id, session
                ),
                route="chat",
            )
            if greets and after is None:
                chat = {
                    "participant_id": participant_id,
                    "session": session,
                    "text": GREETING,
                }
                ws.send("bargain_chat:" + json.dumps(chat))
            view, number, accepted = None, 0, False
            for channel, payload in frames(ws, timeout=0.05):
                if channel == "dallinger_direct":
                    out["chat"].append(payload)
                elif payload is not None and payload.get("type") == "realtime_view":
                    view = payload["view"]["view"]
                elif payload is not None and payload.get("type") == "realtime_saved":
                    out["rounds"].append(dict(payload, session=session))
                    break
                if view is None or (after is None and not out["chat"]):
                    continue
                move = bargain(view, accepted)
                if move:
                    ws.send(game_message("bargain", number, move))
                    number += 1
                    accepted = accepted or "accept" in move
            ws.close()
            after = session
    except Exception as error:
        out["error"] = repr(error)


@pytest.mark.slow
def test_a_pair_chats_and_plays_both_rounds(bargaining_server):
    base = "http://127.0.0.1:{}".format(bargaining_server)
    requests.post(base + "/launch").raise_for_status()
    # The second player's node fills the pair, which starts the first round
    players = [sign_up(base, number) for number in (1, 2)]
    outs = {player: {} for player in players}
    threads = [
        threading.Thread(
            target=play,
            args=(bargaining_server, player, player == players[0], outs[player]),
        )
        for player in players
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert not [o["error"] for o in outs.values() if "error" in o]

    db.session.remove()
    rows = db.session.query(RealtimeSession).order_by(RealtimeSession.id).all()
    assert len(rows) == 2
    for row in rows:
        assert sorted(row.members) == sorted(players)
        assert (row.status, row.end_reason) == ("ended", "finished")
        # A deal is at the seller's cost, so the buyer gets the whole surplus
        roles = {role: int(p) for p, role in row.outcome["roles"].items()}
        cost = row.outcome["values"][str(roles["seller"])]
        value = row.outcome["values"][str(roles["buyer"])]
        assert row.outcome["deal"] == (cost if cost <= value else None)

    # Each page saw both rounds end, the second only after the first
    for player in players:
        rounds = outs[player]["rounds"]
        assert [r["session"] for r in rounds] == [row.id for row in rows]
        assert all(r["reason"] == "finished" for r in rounds)

    # The greeting was saved on the sender's node and relayed to both players
    relayed = {"session": rows[0].id, "from": players[0], "text": GREETING}
    for player in players:
        assert relayed in outs[player]["chat"]
    (info,) = db.session.query(Info).all()
    assert info.contents == GREETING
    assert info.details == {"session": rows[0].id}
    assert info.origin.participant_id == players[0]
