import os
from unittest import mock

import psutil
import pytest

from dallinger.db import db_url_default
from dallinger.heroku.tools import local_worker_processes
from dallinger.pytest_dallinger import clear_workers

THIS_DB = "postgresql://dallinger:dallinger@localhost/this"


def _process(name, cmdline, env=None):
    process = mock.Mock(pid=os.getpid() + 1)
    process.name.return_value = name
    process.cmdline.return_value = cmdline
    if isinstance(env, Exception):
        process.environ.side_effect = env
    else:
        process.environ.return_value = {"DATABASE_URL": THIS_DB} if env is None else env
    return process


@pytest.mark.parametrize(
    "process, expected",
    [
        (_process("dallinger_herok", ["dallinger_heroku_web"]), True),
        (
            _process(
                "python3.13", ["/venv/bin/python", "/venv/bin/dallinger_heroku_worker"]
            ),
            True,
        ),
        (
            _process(
                "dallinger_herok", [], {"DATABASE_URL": "postgres://x@localhost/other"}
            ),
            False,
        ),
        (_process("dallinger_herok", [], psutil.AccessDenied(1)), False),
        (_process("node", ["/usr/lib/heroku/bin/run", "local"]), False),
        (
            _process("python3", ["python", "-m", "pytest", "dallinger_heroku_web"]),
            False,
        ),
    ],
)
def test_local_worker_processes(process, expected):
    with mock.patch("psutil.process_iter", return_value=[process]):
        assert (local_worker_processes(THIS_DB) == [process]) is expected


def test_local_worker_processes_defaults_to_this_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    process = _process("dallinger_herok", [], env={})
    with mock.patch("psutil.process_iter", return_value=[process]):
        assert local_worker_processes() == [process]
        assert local_worker_processes(db_url_default) == [process]
        assert local_worker_processes(THIS_DB) == []


def test_clear_workers_terminates_and_ignores_access_denied():
    process = _process("dallinger_herok", [])
    process.terminate.side_effect = psutil.AccessDenied(process.pid)

    with mock.patch(
        "dallinger.heroku.tools.local_worker_processes", return_value=[process]
    ):
        fixture = clear_workers.__wrapped__()
        next(fixture)
        with pytest.raises(StopIteration):
            next(fixture)

    assert process.terminate.call_count == 2
