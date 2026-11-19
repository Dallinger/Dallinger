import subprocess
import sys

import pytest

EXPERIMENT = """
from dallinger.experiment import Experiment
from dallinger.realtime import RealtimeGame


class Duel(RealtimeGame):
    channel = "duel"

    def initial_state(self, players):
        return {{}}

    def apply(self, state, message, now):
        return state

    def view(self, state, player):
        return state


class Exp(Experiment):
    realtime_games = [{}]
"""


@pytest.mark.slow
@pytest.mark.parametrize("game_type, starts", [("Duel", True), ("object", False)])
def test_the_dev_server_starts_only_with_valid_game_types(tmp_path, game_type, starts):
    (tmp_path / "experiment.py").write_text(EXPERIMENT.format(game_type))
    (tmp_path / "config.txt").write_text("[Experiment]\nmode = debug\n")

    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", "import dallinger.dev_server.app"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert (result.returncode == 0) is starts, result.stderr
    assert ("is not a RealtimeGame subclass" in result.stderr) is not starts


@pytest.mark.slow
@pytest.mark.parametrize("werkzeug_changed", [False, True])
def test_the_dev_server_keeps_its_hub_free_for_queries_and_reloader_scans(
    tmp_path, werkzeug_changed
):
    (tmp_path / "experiment.py").write_text(EXPERIMENT.format("Duel"))
    (tmp_path / "config.txt").write_text("[Experiment]\nmode = debug\n")
    change_werkzeug = (
        "import werkzeug._reloader\ndel werkzeug._reloader._find_stat_paths\n"
    )
    check = (
        (change_werkzeug if werkzeug_changed else "")
        + "import dallinger.dev_server.app, psycopg2.extensions\n"
        "from werkzeug._reloader import StatReloaderLoop\n"
        "print(psycopg2.extensions.get_wait_callback() is not None)\n"
        "print(StatReloaderLoop.run_step.__module__)\n"
    )

    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", check],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    scanner = "werkzeug._reloader" if werkzeug_changed else "dallinger.dev_reloader"
    assert result.stdout.split() == ["True", scanner]
    assert ("stat reloader has changed" in result.stderr) is werkzeug_changed
