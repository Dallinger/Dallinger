import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

import pytest


def test_list_hosts_empty():
    from dallinger.command_line.config import get_configured_hosts

    assert get_configured_hosts() == {}


def test_list_hosts_results(tmp_appdir):
    from dallinger.command_line.config import get_configured_hosts

    (Path(tmp_appdir) / "hosts").mkdir()
    host1 = dict(user="test_user_1", host="test_host_1")
    host2 = dict(user="test_user_2", host="test_host_2")
    (Path(tmp_appdir) / "hosts" / "test_host_1").write_text(json.dumps(host1))
    (Path(tmp_appdir) / "hosts" / "test_host_2").write_text(json.dumps(host2))
    assert get_configured_hosts() == {"test_host_1": host1, "test_host_2": host2}


def test_store_host():
    from dallinger.command_line.config import get_configured_hosts, store_host

    host1 = dict(user="test_user_1", host="test_host_1")
    host2 = dict(user="test_user_2", host="test_host_2")
    store_host(host1), store_host(host2)
    assert get_configured_hosts() == {"test_host_1": host1, "test_host_2": host2}


@pytest.fixture(autouse=True)
def tmp_appdir():
    """Monkey patch appdirs to provede a pristine dirctory to each test"""
    tmp_dir = tempfile.mkdtemp()
    with mock.patch("dallinger.command_line.config.APPDIRS") as mock_appdirs:
        mock_appdirs.user_data_dir = tmp_dir
        yield tmp_dir
    shutil.rmtree(tmp_dir)
