import os
import subprocess
import sys
from pathlib import Path


def run_python(code):
    """Run ``code`` in a fresh interpreter that imports this checkout of Dallinger."""
    repo_root = str(Path(__file__).resolve().parents[1])
    pythonpath = os.pathsep.join(
        filter(None, [repo_root, os.environ.get("PYTHONPATH")])
    )
    env = {**os.environ, "PYTHONPATH": pythonpath}
    return subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )


def test_worker_startup_imports_skip_rq_cli():
    """Importing croniter runs ``file`` in a subprocess, which can hang under gevent."""
    result = run_python(
        "import sys, dallinger.heroku.rq_gevent_worker; "
        "import gevent.queue, redis, rq, dallinger.config, dallinger.utils; "
        "loaded = [m for m in sys.modules "
        "if m.startswith(('croniter', 'rq.cli', 'rq.cron'))]; "
        "sys.exit(f'Loaded: {loaded}' if loaded else 0)"
    )
    assert result.returncode == 0, result.stderr


def test_worker_refuses_to_start_under_rq_2():
    result = run_python(
        "import rq.version; rq.version.VERSION = '2.12.0'; "
        "import dallinger.heroku.rq_gevent_worker"
    )
    assert result.returncode == 1
    assert "requires RQ 3, but RQ 2.12.0 is installed" in result.stderr
