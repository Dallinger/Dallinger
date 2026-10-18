"""The worker's runner supervisor, with a short script standing in for the
runner. Each child appends its pid to a file when it starts.
"""

import logging
import sys
import time

import pytest

from dallinger import experiment
from dallinger.realtime.supervisor import RunnerSupervisor
from dallinger_scripts.worker import experiment_has_realtime_games

pytestmark = pytest.mark.timeout(10)

EXITS = "import os, sys; open(sys.argv[1], 'a').write(f'{os.getpid()}\\n')"

WAITS_FOR_SIGTERM = """
import os, signal, sys, time
open(sys.argv[1], 'a').write(f'{os.getpid()}\\n')
def stopped(*args):
    open(sys.argv[1], 'a').write('stopped\\n')
    sys.exit()
signal.signal(signal.SIGTERM, stopped)
time.sleep(60)
"""


@pytest.fixture
def supervise(tmp_path):
    """Return a function that starts a supervisor of a script, and the path
    of the file the script writes to. Each supervisor is stopped at the end.
    """
    path = tmp_path / "started"
    started = []

    def start(script):
        supervisor = RunnerSupervisor([sys.executable, "-c", script, str(path)])
        supervisor.start()
        started.append(supervisor)
        return supervisor, path

    yield start
    for supervisor in started:
        stop(supervisor)


@pytest.fixture
def quick_restarts(monkeypatch):
    monkeypatch.setattr("dallinger.realtime.supervisor.RESTART_DELAY", 0.01)


def lines(path):
    return path.read_text().splitlines() if path.exists() else []


def wait_until(condition, timeout=10):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def stop(supervisor):
    supervisor.stop()
    supervisor.join()


def test_a_runner_that_exits_is_started_again(supervise, quick_restarts, caplog):
    supervisor, path = supervise(EXITS)

    wait_until(lambda: len(lines(path)) >= 3)
    stop(supervisor)
    assert len(set(lines(path))) == len(lines(path))
    assert "The real-time runner exited with code 0." in caplog.text


def test_stop_passes_sigterm_on_and_starts_no_more(supervise, caplog):
    supervisor, path = supervise(WAITS_FOR_SIGTERM)
    wait_until(lambda: len(lines(path)) == 1)

    stop(supervisor)
    assert lines(path)[1:] == ["stopped"]
    assert "Starting another" not in caplog.text


def test_a_supervisor_stopped_before_it_starts_starts_nothing(tmp_path):
    path = tmp_path / "started"
    supervisor = RunnerSupervisor([sys.executable, "-c", EXITS, str(path)])
    supervisor.stop()
    supervisor.start()

    supervisor.join()
    assert not path.exists()


def test_stop_during_the_restart_delay_starts_no_more(supervise, monkeypatch, caplog):
    monkeypatch.setattr("dallinger.realtime.supervisor.RESTART_DELAY", 60)
    supervisor, path = supervise(EXITS)
    wait_until(lambda: "Starting another in 60 second(s)." in caplog.text)

    stop(supervisor)
    assert len(lines(path)) == 1


def test_a_runner_that_cannot_start_is_tried_again(quick_restarts, caplog):
    supervisor = RunnerSupervisor(["/nonexistent/dallinger_realtime"])
    supervisor.start()

    try:
        wait_until(lambda: caplog.text.count("Couldn't start the real-time") >= 2)
    finally:
        stop(supervisor)
    assert "The real-time runner couldn't start." in caplog.text


class WithGames:
    realtime_games = [object]


class WithoutGames:
    realtime_games = []


def broken():
    raise ImportError("no experiment here")


@pytest.mark.parametrize(
    "load, expected",
    [(lambda: WithGames, True), (lambda: WithoutGames, False), (broken, False)],
)
def test_the_worker_supervises_a_runner_when_the_experiment_has_game_types(
    monkeypatch, caplog, load, expected
):
    monkeypatch.setattr(experiment, "load", load)
    caplog.set_level(logging.ERROR)

    assert experiment_has_realtime_games() is expected
    assert ("no experiment here" in caplog.text) is (load is broken)
