import configparser
import os
import shutil
import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

from dallinger_scripts import worker

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = Path(__file__).parent / "experiment"

WORKER_SCRIPT = """
import time
import dallinger.config
from dallinger_scripts import worker

worker.listen = [{queue!r}]
real_initialize_experiment_package = dallinger.config.initialize_experiment_package

def initialize_experiment_package(path):
    # Runs after main() has started the timer and imported rq_gevent_worker.
    dallinger.config.initialize_experiment_package = real_initialize_experiment_package
    from dallinger.heroku.rq_gevent_worker import GeventWorker

    real_work = GeventWorker.work

    def work(self, logging_level):
{work_body}

    GeventWorker.work = work
    real_initialize_experiment_package(path)

dallinger.config.initialize_experiment_package = initialize_experiment_package
{before_main}
worker.main()
"""


def run_worker(
    tmp_path, work_body="pass", startup_timeout="1", before_main="", extra_config=""
):
    """Run the worker's ``main`` with ``GeventWorker.work`` replaced by ``work_body``.

    ``work_body`` can call the original as ``real_work``. The worker listens
    on a fresh queue, so it doesn't pick up other tests' jobs.
    ``startup_timeout=None`` leaves ``worker_startup_timeout`` out of the
    environment; ``extra_config`` is appended to the experiment's config.txt.
    """
    experiment_dir = shutil.copytree(EXPERIMENT_DIR, tmp_path / "experiment")
    with open(experiment_dir / "config.txt", "a") as config_txt:
        config_txt.write(extra_config)
    script = WORKER_SCRIPT.format(
        queue=f"test_worker_{uuid.uuid4().hex}",
        work_body=textwrap.indent(textwrap.dedent(work_body).strip(), " " * 8),
        before_main=before_main,
    )
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    if startup_timeout is None:
        env.pop("worker_startup_timeout", None)
    else:
        env["worker_startup_timeout"] = startup_timeout
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=experiment_dir,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_worker_that_never_registers_exits_after_startup_timeout(tmp_path):
    result = run_worker(tmp_path, "time.sleep(30)", startup_timeout="5")
    assert result.returncode == 1
    # The announcement is logged at DEBUG, so only loglevel_worker = 0 shows it.
    assert "Worker will exit" not in result.stderr
    assert "hasn't registered with RQ within 5 s; exiting" in result.stderr


def test_debug_log_level_announces_startup_timeout(tmp_path):
    result = run_worker(
        tmp_path, startup_timeout="60", extra_config="loglevel_worker = 0\n"
    )
    assert result.returncode == 0, result.stderr
    assert "Worker will exit if it hasn't registered with RQ within 60 s" in (
        result.stderr
    )


def test_startup_timeout_from_config_txt(tmp_path):
    result = run_worker(
        tmp_path,
        "time.sleep(30)",
        startup_timeout=None,
        extra_config="worker_startup_timeout = 1\n",
    )
    assert result.returncode == 1
    assert "hasn't registered with RQ within 1 s; exiting" in result.stderr
    assert "Raise worker_startup_timeout" in result.stderr


def test_startup_timeout_from_environment_covers_config_loading(tmp_path):
    result = run_worker(
        tmp_path,
        before_main="dallinger.config.get_config = lambda **kwargs: time.sleep(30)",
    )
    assert result.returncode == 1
    assert "hasn't registered with RQ within 1 s; exiting" in result.stderr


def test_zero_startup_timeout_disables_it(tmp_path):
    result = run_worker(tmp_path, "time.sleep(0.5)", startup_timeout="0")
    assert result.returncode == 0, result.stderr
    assert "registered with RQ within" not in result.stderr


def test_worker_start_up_cancels_startup_timeout(tmp_path):
    result = run_worker(
        tmp_path,
        """
        real_work(self, burst=True, logging_level=logging_level)
        time.sleep(6)
        """,
        startup_timeout="5",
    )
    assert result.returncode == 0, result.stderr
    assert "exiting" not in result.stderr


def test_default_startup_timeout_matches_global_config_defaults():
    defaults = configparser.ConfigParser()
    defaults.read(
        REPO_ROOT / "dallinger" / "default_configs" / "global_config_defaults.txt"
    )
    assert defaults.getint("Heroku", "worker_startup_timeout") == (
        worker.DEFAULT_STARTUP_TIMEOUT
    )


@pytest.mark.parametrize("value", [None, "soon", "-1", -1])
def test_invalid_startup_timeout_warns_and_uses_default(value, capsys):
    assert worker._checked_startup_timeout(value) == worker.DEFAULT_STARTUP_TIMEOUT
    assert "Invalid worker_startup_timeout" in capsys.readouterr().err
