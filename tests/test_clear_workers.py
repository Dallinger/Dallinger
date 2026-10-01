import os
import subprocess
import sys
import time

import pytest

from dallinger.db import corrected_db_url, db_url_default
from dallinger.pytest_dallinger import (
    _heroku_processes_for_current_database,
    _is_heroku_process,
)


@pytest.mark.parametrize(
    "cmdline, expected",
    [
        (
            [
                "/usr/local/lib/heroku/bin/node",
                "/usr/local/lib/heroku/bin/run",
                "local",
            ],
            True,
        ),
        (["heroku", "local", "-p", "5000"], True),
        (["/bin/sh", "-c", "dallinger_heroku_web"], True),
        (["/venv/bin/python", "/venv/bin/dallinger_heroku_worker"], True),
        (["python", "-m", "pytest", "tests/test_heroku.py"], False),
        (["git", "push", "heroku", "main"], False),
        (["heroku", "logs", "--tail"], False),
        ([], False),
    ],
)
def test_is_heroku_process(cmdline, expected):
    assert _is_heroku_process(cmdline) is expected


def _start_fake_heroku(tmp_path, database_url):
    script = tmp_path / "heroku" / "run"
    script.parent.mkdir(exist_ok=True)
    script.write_text("import time\ntime.sleep(30)\n")
    env = {**os.environ, "DATABASE_URL": database_url}
    return subprocess.Popen([sys.executable, str(script), "local"], env=env)


def test_clear_workers_only_selects_processes_on_this_database(tmp_path):
    this_db = corrected_db_url(os.environ.get("DATABASE_URL", db_url_default))
    ours = _start_fake_heroku(tmp_path, this_db)
    theirs = _start_fake_heroku(tmp_path, "postgresql://someone@localhost/other")
    try:
        time.sleep(0.5)
        pids = {p.pid for p in _heroku_processes_for_current_database()}
        assert ours.pid in pids
        assert theirs.pid not in pids
    finally:
        for process in (ours, theirs):
            process.kill()
            process.wait()
