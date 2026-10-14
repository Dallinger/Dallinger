import os
import subprocess
import sys
from pathlib import Path


def test_worker_import_does_not_load_croniter():
    """Importing croniter runs ``file`` in a subprocess, which can hang under gevent."""
    code = (
        "import sys, dallinger.heroku.rq_gevent_worker; "
        "import gevent.queue, redis, rq, dallinger.config, dallinger.utils; "
        "loaded = [m for m in sys.modules "
        "if m.startswith(('croniter', 'rq.cli', 'rq.cron'))]; "
        "sys.exit(f'Loaded: {loaded}' if loaded else 0)"
    )
    repo_root = str(Path(__file__).resolve().parents[1])
    pythonpath = os.pathsep.join(
        filter(None, [repo_root, os.environ.get("PYTHONPATH")])
    )
    env = {**os.environ, "PYTHONPATH": pythonpath}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, result.stderr
