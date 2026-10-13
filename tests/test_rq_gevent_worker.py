import subprocess
import sys


def test_worker_import_does_not_load_croniter():
    """Importing croniter runs ``file`` in a subprocess, which can hang under gevent."""
    code = (
        "import sys, dallinger.heroku.rq_gevent_worker; "
        "loaded = [m for m in sys.modules if m.startswith(('croniter', 'rq.cli'))]; "
        "sys.exit(f'Loaded: {loaded}' if loaded else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
