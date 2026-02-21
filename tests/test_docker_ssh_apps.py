import importlib
from unittest import mock

import click
import pytest

docker_ssh_module = importlib.import_module("dallinger.command_line.docker_ssh")


def _mock_executor():
    executor = mock.Mock()
    executor.run.side_effect = [
        "alpha\n/home/test/dallinger/beta/docker-compose.yml\n",
        "beta\n",
    ]
    return executor


def test_get_app_statuses_maps_running_and_inactive():
    statuses = docker_ssh_module.get_app_statuses(
        "irrelevant",
        server_info={"host": "example.com", "user": "ubuntu"},
        executor=_mock_executor(),
    )

    assert statuses == {
        "alpha": {"state": "inactive"},
        "beta": {"state": "running"},
    }


def test_list_server_apps_filters_running_only():
    running = docker_ssh_module.list_server_apps(
        "irrelevant",
        include_stopped=False,
        server_info={"host": "example.com", "user": "ubuntu"},
        executor=_mock_executor(),
    )

    assert running == ["beta"]


def test_list_server_apps_can_include_inactive():
    apps = docker_ssh_module.list_server_apps(
        "irrelevant",
        include_stopped=True,
        server_info={"host": "example.com", "user": "ubuntu"},
        executor=_mock_executor(),
    )

    assert apps == ["alpha", "beta"]


def test_select_running_app_returns_single(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "list_server_apps",
        lambda *args, **kwargs: ["single-app"],
    )
    monkeypatch.setattr(
        docker_ssh_module,
        "Executor",
        lambda host, user=None, app=None: object(),
    )

    selected = docker_ssh_module.select_running_app(
        "irrelevant",
        server_info={"host": "example.com", "user": "ubuntu"},
    )

    assert selected == "single-app"


def test_select_running_app_raises_when_none_running(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module, "list_server_apps", lambda *args, **kwargs: []
    )
    monkeypatch.setattr(
        docker_ssh_module,
        "Executor",
        lambda host, user=None, app=None: object(),
    )

    with pytest.raises(click.UsageError, match="No running apps found"):
        docker_ssh_module.select_running_app(
            "irrelevant",
            server_info={"host": "example.com", "user": "ubuntu"},
        )


def test_select_running_app_raises_when_multiple_running(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "list_server_apps",
        lambda *args, **kwargs: ["app-a", "app-b"],
    )
    monkeypatch.setattr(
        docker_ssh_module,
        "Executor",
        lambda host, user=None, app=None: object(),
    )

    with pytest.raises(ValueError, match="Multiple running apps found"):
        docker_ssh_module.select_running_app(
            "irrelevant",
            server_info={"host": "example.com", "user": "ubuntu"},
        )


def test_get_app_statuses_raises_for_unknown_server(monkeypatch):
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {})

    with pytest.raises(click.UsageError, match="Unknown server"):
        docker_ssh_module.get_app_statuses("missing-server")


def test_select_running_app_raises_value_error_for_unknown_server(monkeypatch):
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {})

    with pytest.raises(ValueError, match="Unknown server"):
        docker_ssh_module.select_running_app("missing-server")


def test_apps_outputs_table_for_all_apps(monkeypatch, capsys):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_app_statuses",
        lambda server: {
            "alpha": {"state": "inactive"},
            "beta": {"state": "running"},
        },
    )

    listed = docker_ssh_module.apps.callback(
        server="irrelevant",
    )

    output_lines = capsys.readouterr().out.strip().splitlines()
    assert listed == ["beta", "alpha"]
    assert any("app" in line and "state" in line for line in output_lines)
    assert any(
        "beta" in line and "running" in line and "\x1b[" in line
        for line in output_lines
    )
    assert any(
        "alpha" in line and "inactive" in line and "\x1b[" in line
        for line in output_lines
    )


def test_apps_outputs_table_when_all_inactive(monkeypatch, capsys):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_app_statuses",
        lambda server: {
            "alpha": {"state": "inactive"},
            "beta": {"state": "inactive"},
        },
    )

    listed = docker_ssh_module.apps.callback(
        server="irrelevant",
    )

    output_lines = capsys.readouterr().out.strip().splitlines()
    assert listed == ["alpha", "beta"]
    assert any("app" in line and "state" in line for line in output_lines)
    assert any(
        "alpha" in line and "inactive" in line and "\x1b[" in line
        for line in output_lines
    )
    assert any(
        "beta" in line and "inactive" in line and "\x1b[" in line
        for line in output_lines
    )
