import json
import shutil
import tempfile
from pathlib import Path

import pytest


def test_list_hosts_empty(tmp_dirs):
    from dallinger.command_line.config import get_configured_hosts

    assert get_configured_hosts() == {}


def test_list_hosts_results(tmp_dirs):
    from dallinger.command_line.config import get_configured_hosts, store_host

    host1 = dict(user="test_user_1", host="test_host_1")
    host2 = dict(user="test_user_2", host="test_host_2")
    store_host(host1)
    store_host(host2)
    assert get_configured_hosts() == {"test_host_1": host1, "test_host_2": host2}


def test_list_hosts_backward_compat(tmp_dirs):
    """Test reading from old location for backward compatibility."""
    from dallinger.command_line.config import OLD_HOSTS_DIR, get_configured_hosts

    OLD_HOSTS_DIR.mkdir(parents=True)
    host = dict(user="test_user", host="test_host")
    (OLD_HOSTS_DIR / "test_host").write_text(json.dumps(host))
    assert get_configured_hosts() == {"test_host": host}


def test_store_host(tmp_dirs):
    from dallinger.command_line.config import get_configured_hosts, store_host

    host1 = dict(user="test_user_1", host="test_host_1")
    host2 = dict(user="test_user_2", host="test_host_2")
    store_host(host1)
    store_host(host2)
    assert get_configured_hosts() == {"test_host_1": host1, "test_host_2": host2}


@pytest.fixture(autouse=True)
def tmp_dirs():
    """Monkey patch the host directory constants to provide pristine directories to each test."""
    tmp_dir = tempfile.mkdtemp()
    tmp_home = tempfile.mkdtemp()

    import dallinger.command_line.config

    original_old_dir = dallinger.command_line.config.OLD_HOSTS_DIR
    original_new_dir = dallinger.command_line.config.NEW_HOSTS_DIR

    dallinger.command_line.config.OLD_HOSTS_DIR = Path(tmp_dir) / "hosts"
    dallinger.command_line.config.NEW_HOSTS_DIR = (
        Path(tmp_home) / ".dallinger" / "docker-ssh" / "hosts"
    )

    yield {"old": tmp_dir, "new": tmp_home}

    dallinger.command_line.config.OLD_HOSTS_DIR = original_old_dir
    dallinger.command_line.config.NEW_HOSTS_DIR = original_new_dir

    shutil.rmtree(tmp_dir)
    shutil.rmtree(tmp_home)
