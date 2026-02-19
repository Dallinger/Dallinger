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


def test_resolve_export_app_auto_selects_single(monkeypatch, capsys):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    server_info = {"host": "example.com"}
    monkeypatch.setattr(docker_ssh, "Executor", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        docker_ssh, "get_existing_remote_experiments", lambda executor: ["only-app"]
    )

    selected = docker_ssh._resolve_export_app(None, "server-1", server_info)

    assert selected == "only-app"
    assert "Auto-selecting app" in capsys.readouterr().out


def test_resolve_export_app_no_apps(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    server_info = {"host": "example.com"}
    monkeypatch.setattr(docker_ssh, "Executor", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        docker_ssh, "get_existing_remote_experiments", lambda executor: []
    )

    with pytest.raises(click.UsageError) as excinfo:
        docker_ssh._resolve_export_app(None, "server-1", server_info)

    message = str(excinfo.value)
    assert "No apps found on server 'server-1'." in message
    assert "dallinger docker-ssh apps --server server-1" in message


def test_resolve_export_app_multiple_apps(monkeypatch):
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    server_info = {"host": "example.com"}
    monkeypatch.setattr(docker_ssh, "Executor", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        docker_ssh,
        "get_existing_remote_experiments",
        lambda executor: ["app-one", "app-two"],
    )

    with pytest.raises(click.UsageError) as excinfo:
        docker_ssh._resolve_export_app(None, "server-1", server_info)

    message = str(excinfo.value)
    assert "Multiple apps found on server 'server-1': app-one, app-two." in message
    assert "Please specify --app" in message


def test_get_existing_remote_experiments_includes_root_domain():
    docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

    class FakeExecutor:
        def run(self, cmd, raise_=True):
            if cmd == "ls -1 ~/dallinger/caddy.d":
                return ""
            if cmd == "ls -1 ~/dallinger":
                return "root-app\ncaddy.d\ndeploy_logs\n"
            if cmd.startswith(
                "test -f ~/dallinger/root-app/docker-compose.yml && echo yes"
            ):
                return "yes\n"
            return ""

    apps = docker_ssh.get_existing_remote_experiments(FakeExecutor())

    assert apps == ["root-app"]
