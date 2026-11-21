import configparser
import os
import re
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
worker.cpu_listen = [{queue!r} + suffix for suffix in ("_cpu_high", "_cpu", "_cpu_low")]
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
worker.main({argv!r})
"""


def run_worker(
    tmp_path,
    work_body="pass",
    startup_timeout="1",
    before_main="",
    extra_config="",
    argv=(),
):
    """Run the worker's ``main`` with ``GeventWorker.work`` replaced by ``work_body``.

    ``work_body`` can call the original as ``real_work``. The worker listens
    on fresh queues, so it doesn't pick up other tests' jobs.
    ``startup_timeout=None`` leaves ``worker_startup_timeout`` out of the
    environment; ``extra_config`` is appended to the experiment's config.txt.
    ``argv`` are the worker's command-line arguments.
    """
    experiment_dir = shutil.copytree(EXPERIMENT_DIR, tmp_path / "experiment")
    with open(experiment_dir / "config.txt", "a") as config_txt:
        config_txt.write(extra_config)
    script = WORKER_SCRIPT.format(
        queue=f"test_worker_{uuid.uuid4().hex}",
        work_body=textwrap.indent(textwrap.dedent(work_body).strip(), " " * 8),
        before_main=before_main,
        argv=list(argv),
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


def test_development_server_worker_uses_the_console_format(tmp_path, monkeypatch):
    monkeypatch.setenv("DALLINGER_DEV_ROLE", "worker")
    result = run_worker(
        tmp_path, startup_timeout="60", extra_config="loglevel_worker = 0\n"
    )
    assert re.search(
        r"^\d\d:\d\d:\d\d worker Worker will exit if", result.stderr, re.MULTILINE
    )


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


def test_worker_runs_jobs_and_keeps_their_executions_past_the_job_timeout(tmp_path):
    result = run_worker(
        tmp_path,
        """
        job = self.queues[0].enqueue("time.sleep", 0, job_timeout=600)
        failing = self.queues[0].enqueue("math.sqrt", -1)
        real_work(self, burst=True, logging_level=logging_level)
        assert job.get_status() == "finished", job.get_status()
        assert failing.get_status() == "failed", failing.get_status()
        assert self.get_heartbeat_ttl(job) > job.timeout
        """,
        startup_timeout="60",
    )
    assert result.returncode == 0, result.stderr


def test_cpu_worker_runs_cpu_jobs_one_at_a_time_by_priority(tmp_path):
    result = run_worker(
        tmp_path,
        """
        assert [queue.name for queue in self.queues] == worker.cpu_listen
        assert self.gevent_pool.size == 1
        high, _, low = self.queues
        low_job = low.enqueue("time.sleep", 0.1)
        high_job = high.enqueue("time.sleep", 0.1)
        real_work(self, burst=True, logging_level=logging_level)
        for job in (low_job, high_job):
            job.refresh()
            assert job.get_status() == "finished", job.get_status()
        assert high_job.ended_at <= low_job.started_at
        """,
        startup_timeout="60",
        argv=["--cpu"],
    )
    assert result.returncode == 0, result.stderr


def test_busy_cpu_worker_keeps_its_registration_alive(tmp_path):
    result = run_worker(
        tmp_path,
        """
        import gevent
        self.worker_ttl = 2
        beats = []
        real_heartbeat = self.heartbeat
        def heartbeat(*args, **kwargs):
            beats.append(time.monotonic())
            return real_heartbeat(*args, **kwargs)
        self.heartbeat = heartbeat
        job = self.queues[0].enqueue("time.sleep", 3)
        started = time.monotonic()
        real_work(self, burst=True, logging_level=logging_level)
        assert job.get_status() == "finished", job.get_status()
        assert len([b for b in beats if started + 0.5 < b < started + 2.9]) >= 2, beats
        """,
        startup_timeout="60",
        argv=["--cpu"],
    )
    assert result.returncode == 0, result.stderr


def test_cpu_worker_finishes_its_job_despite_a_second_signal(tmp_path):
    # Heroku sends SIGTERM to every process; the parent worker sends another.
    result = run_worker(
        tmp_path,
        """
        import os, signal
        import gevent
        job = self.queues[0].enqueue("time.sleep", 1)
        gevent.spawn_later(0.5, os.kill, os.getpid(), signal.SIGTERM)
        gevent.spawn_later(0.51, os.kill, os.getpid(), signal.SIGTERM)
        assert real_work(self, logging_level=logging_level) is True
        assert job.get_status() == "finished", job.get_status()
        assert not self.connection.sismember(self.redis_workers_keys, self.key)
        """,
        startup_timeout="60",
        argv=["--cpu"],
    )
    assert result.returncode == 0, result.stderr
    assert "StopRequested" not in result.stderr, result.stderr


CPU_WORKER_STAND_IN = """
import os, signal, sys, time
def stopped(*args):
    open(sys.argv[1], 'a').write('stopped\\n')
    sys.exit()
signal.signal(signal.SIGTERM, stopped)
open(sys.argv[1], 'a').write(f'{os.getpid()}\\n')
time.sleep(60)
"""


def test_worker_keeps_cpu_workers_going_and_stops_them_when_it_stops(tmp_path):
    started = tmp_path / "started"
    result = run_worker(
        tmp_path,
        f"""
        deadline = time.monotonic() + 5
        while not (
            os.path.exists({str(started)!r})
            and len(open({str(started)!r}).read().split()) >= 2
        ):
            assert time.monotonic() < deadline, "CPU workers didn't start"
            time.sleep(0.05)
        """,
        startup_timeout="60",
        before_main=(
            "import os, sys\n"
            f"worker.CPU_WORKER_COMMAND = (sys.executable, '-c', "
            f"{CPU_WORKER_STAND_IN!r}, {str(started)!r})"
        ),
        extra_config="cpu_processes_per_worker = 2\n",
    )
    assert result.returncode == 0, result.stderr
    lines = started.read_text().split()
    assert len([line for line in lines if line.isdigit()]) == 2
    assert lines.count("stopped") == 2


def test_cpu_worker_starts_no_cpu_workers_of_its_own(tmp_path):
    started = tmp_path / "started"
    result = run_worker(
        tmp_path,
        "time.sleep(1)",
        startup_timeout="60",
        before_main=(
            "import os, sys\n"
            f"worker.CPU_WORKER_COMMAND = (sys.executable, '-c', "
            f"{CPU_WORKER_STAND_IN!r}, {str(started)!r})"
        ),
        extra_config="cpu_processes_per_worker = 2\n",
        argv=["--cpu"],
    )
    assert result.returncode == 0, result.stderr
    assert not started.exists()


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
