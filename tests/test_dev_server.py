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
