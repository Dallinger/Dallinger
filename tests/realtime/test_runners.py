"""Runners in processes of their own, stopped and killed while they play.

Each runner imports Dallinger and, except where a test runs the
``dallinger_realtime`` or ``dallinger_heroku_worker`` script, plays with
claims that last a second.
"""

import json
import os
import signal
import subprocess
import sys
import time

import psutil
import pytest

from dallinger.db import REALTIME_SESSION_CHANNEL, get_queue
from dallinger.realtime import store, supervisor
from dallinger.realtime.game import FAILED
from dallinger.realtime.runner import owner
from tests.realtime.helpers import add, handovers, join, message

pytestmark = [pytest.mark.slow, pytest.mark.timeout(120)]

SCRATCH_EXPERIMENT = """
import time

from dallinger.experiment import Experiment
from dallinger.realtime import RealtimeGame


class Counter(RealtimeGame):
    channel = "counter"

    def initial_state(self, players):
        return {"seen": []}

    def apply(self, state, player_id, message, now, sent):
        if message == "nap":
            time.sleep(0.3)
        while message == "spin":
            pass
        state["seen"].append(message)

    def view(self, state, player_id):
        return {"seen": len(state["seen"])}


class Looper(Counter):
    channel = "looper"
    time_limit = 0.2

    def apply(self, state, player_id, message, now, sent):
        while True:
            try:
                while True:
                    pass
            except BaseException:
                pass


class Scratch(Experiment):
    realtime_games = [Counter, Looper]
"""

RUN_RUNNER = """
from dallinger.realtime import runner

runner.CLAIM_TTL = runner.HEARTBEAT_TTL = 1
runner.SESSION_RENEW_INTERVAL = 1 / 3
runner.CLAIM_INTERVAL = 0.1

from dallinger_scripts.realtime import main

main()
"""

# The worker finds dallinger_realtime on PATH, as the Procfile finds the worker.
BIN = os.path.dirname(sys.executable)
SCRIPT = os.path.join(BIN, "dallinger_realtime")
WORKER = os.path.join(BIN, "dallinger_heroku_worker")

scratch = {}
exec(SCRATCH_EXPERIMENT, scratch)
Counter, Looper = scratch["Counter"], scratch["Looper"]


@pytest.fixture
def start_runner(tmp_path, realtime_experiment, redis_conn):
    """Return a function that starts a runner process, or a worker, and waits
    for its runner to count as running. The processes are killed before redis
    is emptied, so none leaves a key behind.
    """
    realtime_experiment.realtime_games = [Counter, Looper]
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "experiment.py").write_text(SCRATCH_EXPERIMENT)
    (tmp_path / "run_runner.py").write_text(RUN_RUNNER)
    processes = []

    def start(command=(sys.executable, "run_runner.py")):
        log_path = tmp_path / "runner-{}.log".format(len(processes))
        with open(log_path, "w") as log:
            process = subprocess.Popen(
                command,
                cwd=tmp_path,
                stdout=log,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PATH": BIN + os.pathsep + os.environ["PATH"]},
            )
        process.log_path = log_path
        processes.append(process)
        wait_until(lambda: runner_pids(process))
        return process

    yield start
    for process in processes:
        if process.poll() is None:
            for child in psutil.Process(process.pid).children():
                child.kill()
            process.send_signal(signal.SIGCONT)
            process.kill()
        process.wait()


def wait_until(condition, timeout=20):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.05)


def pid_of(runner):
    # A runner is named <host>-<pid>-<random>.
    return int(runner.rsplit("-", 2)[1])


def runner_pids(process):
    """The pids of the running runners that are the process or its children."""
    pids = {process.pid} | {
        child.pid for child in psutil.Process(process.pid).children()
    }
    return pids & set(map(pid_of, runner_names()))


def runner_names():
    return [name.decode() for name in store.redis_conn.zrange(store.RUNNERS, 0, -1)]


def holder(session_id):
    """The pid of the runner holding the session's claim, or ``None``."""
    claim = store.redis_conn.get(store.session_key(session_id, "claim"))
    return None if claim is None else pid_of(claim.decode().split(":", 1)[1])


def settled(sessions, processes):
    """Whether each of the running processes is counted, and each session is
    held by the one it belongs to.
    """
    names = runner_names()
    return sorted(map(pid_of, names)) == sorted(each.pid for each in processes) and all(
        holder(each) == pid_of(owner(each, names)) for each in sessions
    )


def new_sessions(game_type, count):
    sessions = [store.create_realtime_session(game_type, ["1"]) for _ in range(count)]
    for session_id in sessions:
        add(session_id, join(0, "1"))
    return sessions


def seen(session_id):
    return store.realtime_state(session_id)["seen"]


def send(sessions, numbers, pause=0.02):
    for number in numbers:
        for session_id in sessions:
            add(session_id, message(0, "1", number))
        time.sleep(pause)


def views_sent(listener):
    """Return a ``(pid, clock)`` pair for each view the runners sent, read
    for half a second, where ``clock`` is when the runner's pass started.
    """
    sent = []
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        frame = listener.get_message(timeout=0.1)
        if frame is None:
            continue
        batch = json.loads(frame["data"])
        for item in batch["items"]:
            view = json.loads(item["payload"])["view"]
            sent.append((pid_of(batch["origin"]), view["clock"]))
    return sent


def test_the_runner_script_plays_with_time_limits_until_it_is_stopped(start_runner):
    session_id, spinning = new_sessions(Counter, 2)
    send([session_id], ["hello"])
    send([spinning], ["spin"])
    process = start_runner([SCRIPT])

    wait_until(
        lambda: (
            store.running_sessions() == [session_id] and seen(session_id) == ["hello"]
        ),
        timeout=30,
    )
    process.send_signal(signal.SIGTERM)
    assert process.wait(10) == 0
    log = process.log_path.read_text()
    assert "Session {} of counter failed".format(spinning) in log
    assert "TimeLimitExceeded: Counter.apply was running" in log


def test_the_worker_restarts_its_runner_and_waits_for_it_to_stop(start_runner):
    worker = start_runner([WORKER])
    [killed] = runner_pids(worker)
    os.kill(killed, signal.SIGKILL)
    wait_until(lambda: runner_pids(worker) - {killed}, timeout=30)
    [stopped] = runner_pids(worker) - {killed}

    worker.send_signal(signal.SIGTERM)
    assert worker.wait(10) == 0
    assert not psutil.pid_exists(stopped)
    assert stopped not in map(pid_of, runner_names())


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGINT])
def test_the_worker_passes_its_stop_signal_on_while_it_finishes_a_job(
    start_runner, signum
):
    worker = start_runner([WORKER])
    [stopped] = runner_pids(worker)
    job = get_queue().enqueue("time.sleep", 60)
    wait_until(lambda: job.get_status() == "started")

    worker.send_signal(signum)
    wait_until(lambda: stopped not in map(pid_of, runner_names()), timeout=10)
    time.sleep(supervisor.RESTART_DELAY + 0.5)
    assert worker.poll() is None
    assert psutil.Process(worker.pid).children() == []


def test_a_killed_runners_sessions_play_on_without_losing_a_message(start_runner):
    started = [start_runner(), start_runner()]
    sessions = new_sessions(Counter, 6)
    wait_until(lambda: settled(sessions, started))
    killed, survivor = sorted(started, key=lambda each: each.pid != holder(sessions[0]))
    send(sessions, range(1, 21))

    killed.kill()
    send(sessions, range(21, 41), pause=0.05)

    wait_until(lambda: all(seen(each) == list(range(1, 41)) for each in sessions))
    assert {holder(each) for each in sessions} == {survivor.pid}
    assert store.running_sessions() == sessions
    assert [handovers(each) for each in sessions] == [0] * 6


def test_a_runner_that_wakes_after_its_claims_expired_cannot_save_or_send(
    start_runner,
):
    """The runner is frozen partway through a pass, and the other runner
    takes the session over. Nothing from that pass reaches redis or the
    pages. The session belongs to the frozen runner once it's running again,
    so it takes the session back with a new claim.
    """
    started = [start_runner(), start_runner()]
    [session_id] = new_sessions(Counter, 1)
    wait_until(lambda: settled([session_id], started))
    frozen, other = sorted(started, key=lambda each: each.pid != holder(session_id))
    send([session_id], [1])
    wait_until(lambda: seen(session_id) == [1])
    listener = store.redis_conn.pubsub(ignore_subscribe_messages=True)
    listener.subscribe(REALTIME_SESSION_CHANNEL)
    views_sent(listener)
    send([session_id], ["nap"])
    time.sleep(0.1)

    frozen_at = store.server_time()
    frozen.send_signal(signal.SIGSTOP)
    wait_until(lambda: holder(session_id) == other.pid)
    frozen.send_signal(signal.SIGCONT)
    wait_until(lambda: seen(session_id) == [1, "nap"])
    # On a slow machine the runner can be past the point where it gives up on
    # the game code, and exit instead.
    wait_until(
        lambda: (
            "lost its claim on session" in frozen.log_path.read_text()
            or frozen.poll() is not None
        )
    )
    send([session_id], [3])
    wait_until(lambda: seen(session_id) == [1, "nap", 3])

    sent = views_sent(listener)
    listener.close()
    assert other.pid in {pid for pid, _ in sent}
    assert [
        clock for pid, clock in sent if pid == frozen.pid and clock < frozen_at
    ] == []


def test_a_restarted_runner_gets_its_sessions_back(start_runner):
    """A runner stopped while game code runs finishes the pass, saves it and
    gives its sessions up before it exits.
    """
    started = [start_runner(), start_runner()]
    sessions = new_sessions(Counter, 12)
    wait_until(lambda: settled(sessions, started))
    stopped, kept = sorted(started, key=lambda each: each.pid != holder(sessions[0]))
    send([sessions[0]], ["nap"])
    time.sleep(0.2)

    stopped.send_signal(signal.SIGTERM)
    assert stopped.wait(10) == 0
    assert stopped.pid not in {holder(each) for each in sessions}
    wait_until(lambda: {holder(each) for each in sessions} == {kept.pid})
    restarted = start_runner()
    wait_until(lambda: settled(sessions, [kept, restarted]))
    send(sessions, [1])

    wait_until(lambda: all(seen(each)[-1:] == [1] for each in sessions))
    assert seen(sessions[0]) == ["nap", 1]
    assert {holder(each) for each in sessions} == {kept.pid, restarted.pid}
    assert store.running_sessions() == sessions


def test_a_session_that_keeps_stopping_its_runners_fails(start_runner):
    """A supervisor restarts each runner that exits, as the worker does."""
    running = [start_runner(), start_runner()]
    exited = []
    [looping] = new_sessions(Looper, 1)
    wait_until(lambda: holder(looping) is not None)
    send([looping], ["spin"])

    deadline = time.monotonic() + 60
    while looping in store.running_sessions():
        assert time.monotonic() < deadline, "timed out"
        for index, process in enumerate(running):
            if process.poll() is not None:
                exited.append(process)
                running[index] = start_runner()
        time.sleep(0.05)

    assert exited and all(process.returncode == 1 for process in exited)
    final = json.loads(store.redis_conn.get(store.session_key(looping, "final")))
    assert final["reason"] == FAILED
    logs = "".join(each.log_path.read_text() for each in exited + running)
    assert "changed runners 3 times without" in logs
    [later] = new_sessions(Counter, 1)
    send([later], [1])
    wait_until(lambda: seen(later) == [1])
    assert store.running_sessions() == [later]
