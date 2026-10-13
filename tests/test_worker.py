import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EXPERIMENT_DIR = Path(__file__).parent / "experiment"


def run_worker(tmp_path, work_body="pass", startup_timeout="1", before_main=""):
    """Run the worker's ``main`` with ``GeventWorker.work`` replaced by ``work_body``."""
    experiment_dir = shutil.copytree(EXPERIMENT_DIR, tmp_path / "experiment")
    script = textwrap.dedent(
        """
        import time
        import dallinger.config
        from dallinger.heroku.rq_gevent_worker import GeventWorker
        from dallinger_scripts import worker

        def work(self, logging_level):
        {}

        GeventWorker.work = work
        {}
        worker.main()
        """
    ).format(textwrap.indent(textwrap.dedent(work_body), "    "), before_main)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=experiment_dir,
        env={
            **os.environ,
            "PYTHONPATH": str(REPO_ROOT),
            "worker_startup_timeout": startup_timeout,
        },
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_worker_that_never_registers_exits_after_startup_timeout(tmp_path):
    result = run_worker(tmp_path, "time.sleep(30)", startup_timeout="5")
    assert result.returncode == 1
    assert (
        "Worker will exit if it hasn't registered with RQ within 5 s" in result.stderr
    )
    assert "hasn't registered with RQ within 5 s; exiting" in result.stderr


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


def test_registration_cancels_startup_timeout(tmp_path):
    result = run_worker(
        tmp_path,
        """
        self.register_birth()
        time.sleep(6)
        self.register_death()
        """,
        startup_timeout="5",
    )
    assert result.returncode == 0, result.stderr
    assert "exiting" not in result.stderr
