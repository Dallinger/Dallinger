from pathlib import Path

import yaml


def test_get_docker_compose_yml_extra_config():
    """Make sure all values passed in config make their way to the
    web and worker container environment
    """
    result = get_yaml({"foo": "bar"})
    assert result["services"]["web"]["environment"]["foo"] == "bar"


def test_get_docker_compose_yml_core_config():
    """Make sure worker and web services have the necessary variables to run"""
    result = get_yaml({})
    assert "REDIS_URL" in result["services"]["worker_1"]["environment"]
    assert "DATABASE_URL" in result["services"]["worker_1"]["environment"]
    assert "HOME" in result["services"]["worker_1"]["environment"]


def test_get_docker_compose_yml_env_vars_always_strings():
    """The docker-compose.yml file we generate should always have strings as
    values in the `environment` section of each service.
    """
    result = get_yaml({"foo": True, "bar": 2})
    assert result["services"]["worker_1"]["environment"]["foo"] == "True"
    assert result["services"]["worker_1"]["environment"]["bar"] == "2"


def test_get_docker_compose_yml_env_vars_escaping():
    """Environment vars with special character should be correctly escaped."""
    result = get_yaml(
        {
            "foo": r'" a quote and a \ backslash ',
            "bar": "Dollar signs should be escaped with another dollar sign: $1.50",
        }
    )
    assert (
        result["services"]["worker_1"]["environment"]["foo"]
        == r'" a quote and a \ backslash '
    )

    assert (
        result["services"]["worker_1"]["environment"]["bar"]
        == "Dollar signs should be escaped with another dollar sign: $$1.50"
    )


def test_add_image_name(tempdir):
    from dallinger.command_line.docker import add_image_name

    file = Path(tempdir) / "test.txt"

    file.write_text("")
    add_image_name(str(file), "foobar")
    assert "docker_image_name = foobar" in file.read_text()

    file.write_text("\ndocker_image_name = old_image_name\n")
    add_image_name(str(file), "new_image_name")
    assert "old_image_name" not in file.read_text()
    assert "docker_image_name = new_image_name" in file.read_text()

    file.write_text(
        "foo = bar\ndocker_image_base_name = the_base_image_name\nbar = foo"
    )
    add_image_name(str(file), "foobar_image")
    assert (
        file.read_text()
        == "foo = bar\ndocker_image_base_name = the_base_image_name\ndocker_image_name = foobar_image\nbar = foo"
    )


def get_yaml(config):
    from dallinger.command_line.docker_ssh import get_docker_compose_yml

    yaml_contents = get_docker_compose_yml(
        config, "dlgr-8c43a887", "ghcr.io/dallinger/dallinger/bartlett1932", "foobar"
    )
    return yaml.safe_load(yaml_contents)


def test_num_dynos():
    """Make sure the correct number of worker services is created"""
    n = 3
    result = get_yaml({"num_dynos_worker": n})
    for i in range(n):
        assert f"worker_{i + 1}" in result["services"]


def test_split_ssh_host_port():
    from dallinger.command_line.docker_ssh import split_ssh_host_port

    assert split_ssh_host_port("example.com") == ("example.com", 22)
    assert split_ssh_host_port("localhost:2222") == ("localhost", 2222)


def test_is_loopback_host():
    from dallinger.command_line.docker_ssh import is_loopback_host

    assert is_loopback_host("localhost")
    assert is_loopback_host("127.0.0.2")
    assert not is_loopback_host("203.0.113.10")


def test_get_connected_ssh_client_creates_missing_known_hosts(tmp_path, monkeypatch):
    import importlib

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    key_path = tmp_path / "server.pem"
    key_path.write_text("dummy")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(docker_ssh, "get_server_pem_path", lambda: key_path)

    class DummySpinner:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def ok(self, *_):
            return None

        def fail(self, *_):
            return None

        def stop(self):
            return None

        def start(self):
            return None

    monkeypatch.setattr(docker_ssh, "yaspin", lambda *args, **kwargs: DummySpinner())

    class DummyClient:
        def load_host_keys(self, filename):
            if not Path(filename).exists():
                raise IOError("missing")

        def set_missing_host_key_policy(self, policy):
            return None

        def load_system_host_keys(self):
            return None

        def connect(self, **kwargs):
            return None

        def save_host_keys(self, filename):
            assert Path(filename).exists()

    monkeypatch.setattr(docker_ssh.paramiko, "SSHClient", DummyClient)

    client = docker_ssh.get_connected_ssh_client("localhost:2222", user="root")
    assert isinstance(client, DummyClient)
    assert (tmp_path / ".ssh" / "known_hosts").exists()
