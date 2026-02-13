import importlib
from pathlib import Path

import click
import pytest
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


def test_detect_postgresql_major_version_mismatch():
    from dallinger.command_line.docker_ssh import (
        detect_postgresql_major_version_mismatch,
    )

    logs = (
        "FATAL:  database files are incompatible with server\n"
        "DETAIL:  The data directory was initialized by PostgreSQL version 12, "
        "which is not compatible with this version 16.12."
    )
    assert detect_postgresql_major_version_mismatch(logs) == ("12", "16")


def test_detect_postgresql_major_version_mismatch_returns_none_without_marker():
    from dallinger.command_line.docker_ssh import (
        detect_postgresql_major_version_mismatch,
    )

    assert detect_postgresql_major_version_mismatch("database system is ready") is None


def test_parse_postgresql_major_from_pg_version():
    from dallinger.command_line.docker_ssh import parse_postgresql_major_from_pg_version

    assert parse_postgresql_major_from_pg_version("12\n") == "12"


def test_parse_postgresql_major_from_pg_version_invalid():
    from dallinger.command_line.docker_ssh import parse_postgresql_major_from_pg_version

    assert parse_postgresql_major_from_pg_version("12.1\n") is None
    assert parse_postgresql_major_from_pg_version("") is None


def test_get_running_app_containers_filters_core_services():
    from dallinger.command_line.docker_ssh import get_running_app_containers

    class ExecutorStub:
        def run(self, cmd, raise_=True):
            del raise_
            assert "docker ps" in cmd
            return "\n".join(
                (
                    "dozzle",
                    "dallinger-postgresql-1",
                    "dallinger_httpserver_1",
                    "psynet-06_web_1",
                    "psynet-06_pgbouncer",
                )
            )

    assert get_running_app_containers(ExecutorStub()) == [
        "psynet-06_web_1",
        "psynet-06_pgbouncer",
    ]


def test_ensure_postgresql_compatibility_or_abort_aborts_on_version_mismatch(
    monkeypatch,
):
    from dallinger.command_line.docker_ssh import (
        ensure_postgresql_compatibility_or_abort,
    )

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    monkeypatch.setattr(
        docker_ssh, "get_postgresql_data_volume_major", lambda executor: "12"
    )

    with pytest.raises(click.Abort):
        ensure_postgresql_compatibility_or_abort(
            object(), server="myserver", expected_major="16"
        )


def test_ensure_postgresql_compatibility_or_abort_allows_matching_version(monkeypatch):
    from dallinger.command_line.docker_ssh import (
        ensure_postgresql_compatibility_or_abort,
    )

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    monkeypatch.setattr(
        docker_ssh, "get_postgresql_data_volume_major", lambda executor: "16"
    )
    ensure_postgresql_compatibility_or_abort(
        object(), server="myserver", expected_major="16"
    )


def test_ensure_postgresql_compatibility_or_abort_allows_missing_volume_version(
    monkeypatch,
):
    from dallinger.command_line.docker_ssh import (
        ensure_postgresql_compatibility_or_abort,
    )

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
    monkeypatch.setattr(
        docker_ssh, "get_postgresql_data_volume_major", lambda executor: None
    )
    ensure_postgresql_compatibility_or_abort(
        object(), server="myserver", expected_major="16"
    )


def test_ensure_postgresql_compatibility_or_abort_uses_log_fallback(monkeypatch):
    from dallinger.command_line.docker_ssh import (
        ensure_postgresql_compatibility_or_abort,
    )

    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    def fail_probe(executor):
        raise RuntimeError("probe failed")

    monkeypatch.setattr(docker_ssh, "get_postgresql_data_volume_major", fail_probe)

    class ExecutorStub:
        def run(self, cmd, raise_=True):
            del raise_
            assert "logs --tail=200 postgresql" in cmd
            return (
                "FATAL: database files are incompatible with server\n"
                "DETAIL: The data directory was initialized by PostgreSQL version 12, "
                "which is not compatible with this version 16.12."
            )

    with pytest.raises(click.Abort):
        ensure_postgresql_compatibility_or_abort(
            ExecutorStub(), server="myserver", expected_major="16"
        )


def test_reset_db_aborts_if_apps_running(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    monkeypatch.setattr(
        docker_ssh,
        "CONFIGURED_HOSTS",
        {"srv": {"host": "example.org", "user": "ubuntu"}},
    )

    class ExecutorStub:
        def run(self, cmd, raise_=True):
            del cmd, raise_
            return ""

    monkeypatch.setattr(
        docker_ssh, "Executor", lambda host, user=None, app=None: ExecutorStub()
    )
    monkeypatch.setattr(
        docker_ssh, "get_running_app_containers", lambda executor: ["psynet-06_web_1"]
    )

    with pytest.raises(click.Abort):
        docker_ssh.reset_db.callback(server="srv")


def test_reset_db_requires_confirmation(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    monkeypatch.setattr(
        docker_ssh,
        "CONFIGURED_HOSTS",
        {"srv": {"host": "example.org", "user": "ubuntu"}},
    )

    commands = []

    class ExecutorStub:
        def run(self, cmd, raise_=True):
            del raise_
            commands.append(cmd)
            return ""

    monkeypatch.setattr(
        docker_ssh, "Executor", lambda host, user=None, app=None: ExecutorStub()
    )
    monkeypatch.setattr(docker_ssh, "get_running_app_containers", lambda executor: [])
    monkeypatch.setattr(click, "confirm", lambda *args, **kwargs: False)

    with pytest.raises(click.Abort):
        docker_ssh.reset_db.callback(server="srv")

    assert commands == []


def test_reset_db_executes_reset_sequence(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    monkeypatch.setattr(
        docker_ssh,
        "CONFIGURED_HOSTS",
        {"srv": {"host": "example.org", "user": "ubuntu"}},
    )

    commands = []

    class ExecutorStub:
        def run(self, cmd, raise_=True):
            del raise_
            commands.append(cmd)
            return ""

    monkeypatch.setattr(
        docker_ssh, "Executor", lambda host, user=None, app=None: ExecutorStub()
    )
    monkeypatch.setattr(docker_ssh, "get_running_app_containers", lambda executor: [])
    monkeypatch.setattr(click, "confirm", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        docker_ssh,
        "get_single_postgresql_data_volume",
        lambda executor, required=False: "dallinger_pg_data",
    )
    docker_ssh.reset_db.callback(server="srv")

    assert commands == [
        "docker compose -f ~/dallinger/docker-compose.yml down",
        "docker volume rm dallinger_pg_data",
    ]
