"""Two players play the coins demo over real websockets, through every part of
the real-time engine: a web process, the runner a worker starts beside it, the
worker's jobs that write the record, and Postgres.

It's slow, so it runs only with ``--runslow``, and needs redis and Postgres.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import requests
import simple_websocket

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession

COINS = Path(__file__).parent.parent / "dlgr" / "demos" / "coins"
BIN = Path(sys.executable).parent

#: Seconds each player has to collect a coin.
PLAY_SECONDS = 45


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(check, seconds, what):
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for {}.".format(what))
        time.sleep(0.1)


def port_open(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


@pytest.fixture
def coins_server(tmp_path):
    """Run the coins demo's web process and worker, and return the web
    process's port. Their logs are printed afterwards, which pytest shows if
    the test fails."""
    directory = tmp_path / "coins"
    shutil.copytree(COINS, directory, ignore=shutil.ignore_patterns("*.log"))
    port = free_port()
    env = {
        **os.environ,
        "PATH": str(BIN) + os.pathsep + os.environ.get("PATH", ""),
        "DATABASE_URL": db.db_url,
        "FLASK_SECRET_KEY": os.urandom(16).hex(),
        "PORT": str(port),
        "SKIP_PYTHON_VERSION_CHECK": "1",
        "mode": "debug",
        "threads": "1",
    }
    db.init_db(drop_all=True)
    processes = {}
    for name in ("web", "worker"):
        with open(directory / (name + ".log"), "w") as log:
            processes[name] = subprocess.Popen(
                [str(BIN / ("dallinger_heroku_" + name))],
                cwd=directory,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    try:
        wait_for(lambda: port_open(port), 60, "the web process")
        yield port
    finally:
        for process in processes.values():
            process.terminate()
        for process in processes.values():
            try:
                process.wait(15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, 9)
        for name in processes:
            print("--- {}.log ---".format(name))
            print((directory / (name + ".log")).read_text(errors="replace"))
        db.session.remove()


def sign_up(base, number):
    """Create a participant and their node, as the instructions page does, and
    return the participant's id."""
    url = "{}/participant/worker{}/hit/assignment{}/debug?recruiter=hotair".format(
        base, number, number
    )
    response = requests.post(url)
    response.raise_for_status()
    participant_id = response.json()["participant"]["id"]
    requests.post("{}/node/{}".format(base, participant_id)).raise_for_status()
    return participant_id


def connect(port, query):
    ws = simple_websocket.Client.connect(
        "ws://127.0.0.1:{}/experiment-socket?{}".format(port, query)
    )
    # As browsers do; otherwise small frames can wait on delayed ACKs
    ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return ws


def frames(ws, timeout):
    """Each frame's payload, as JSON, or ``None`` when ``timeout`` passes with
    no frame."""
    while True:
        frame = ws.receive(timeout=timeout)
        yield None if frame is None else json.loads(frame.partition(":")[2])


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
        waiting = connect(
            port,
            "participant_id={}&scope=wait&wait_for_game=coins".format(participant_id),
        )
        for payload in frames(waiting, timeout=30):
            assert payload is not None, "no session started"
            if payload.get("type") == "realtime_started":
                out["session"] = payload["session_id"]
                break
        waiting.close()

        ws = connect(
            port,
            "participant_id={}&scope=page&session={}".format(
                participant_id, out["session"]
            ),
        )
        number = 0
        for payload in frames(ws, timeout=0.05):
            if payload is not None and payload.get("type") == "realtime_view":
                envelope = payload["view"]
                out["view"] = envelope["view"]
                out["acknowledged"] = envelope["last_processed"]
            elif payload is not None and payload.get("type") == "realtime_saved":
                out["saved"] = payload
                break
            move = "view" in out and steer(out["view"])
            if move:
                sent = {
                    "number": number,
                    "browser_time": time.time(),
                    "view_time": None,
                }
                ws.send("coins:" + json.dumps({"envelope": sent, "payload": move}))
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
