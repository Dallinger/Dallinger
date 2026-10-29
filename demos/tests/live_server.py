"""Helpers for tests that play a real-time demo over real websockets: they run
the demo's web process and worker, sign participants up over HTTP, and open
sockets the way the client helpers do."""

import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

import requests
import simple_websocket

from dallinger import db

BIN = Path(sys.executable).parent


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


@contextlib.contextmanager
def demo_server(demo, tmp_path, settings=None):
    """Run the web process and worker of the demo in the ``demo`` directory,
    with ``settings`` overriding its config.txt, and yield the web process's
    port. Their logs are printed afterwards, which pytest shows if the test
    fails."""
    directory = tmp_path / demo.name
    shutil.copytree(demo, directory, ignore=shutil.ignore_patterns("*.log"))
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
        **(settings or {}),
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


def connect(port, query, route="experiment-socket"):
    ws = simple_websocket.Client.connect(
        "ws://127.0.0.1:{}/{}?{}".format(port, route, query)
    )
    # As browsers do; otherwise small frames can wait on delayed ACKs
    ws.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return ws


def frames(ws, timeout):
    """Each frame's channel and payload, as JSON, or ``(None, None)`` when
    ``timeout`` passes with no frame."""
    while True:
        frame = ws.receive(timeout=timeout)
        if frame is None:
            yield None, None
        else:
            channel, _, payload = frame.partition(":")
            yield channel, json.loads(payload)


def wait_for_session(port, participant_id, game, after=None):
    """Wait for the player's next session of ``game``, as
    ``waitForRealtimeSession`` does, and return its id."""
    query = "participant_id={}&scope=wait&wait_for_game={}".format(participant_id, game)
    if after is not None:
        query += "&after_session={}".format(after)
    waiting = connect(port, query)
    try:
        for _, payload in frames(waiting, timeout=30):
            assert payload is not None, "no session started"
            if payload.get("type") == "realtime_started":
                return payload["session_id"]
    finally:
        waiting.close()


def game_message(channel, number, payload):
    """A frame that sends ``payload`` to the game, as ``socket.send`` does."""
    envelope = {"number": number, "browser_time": time.time(), "view_time": None}
    return channel + ":" + json.dumps({"envelope": envelope, "payload": payload})
