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


def test_get_apps_maps_running_and_inactive():
    executor = _mock_executor()
    server_info = {"host": "example.com", "user": "ubuntu"}
    with (
        mock.patch.object(
            docker_ssh_module, "_resolve_server_info", return_value=server_info
        ),
        mock.patch.object(docker_ssh_module, "_build_executor", return_value=executor),
    ):
        apps = docker_ssh_module.get_apps("irrelevant")

    assert apps == [
        docker_ssh_module.App(name="alpha", state="inactive"),
        docker_ssh_module.App(name="beta", state="running"),
    ]


def test_select_running_app_returns_single(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_apps",
        lambda *args, **kwargs: [
            docker_ssh_module.App(name="single-app", state="running")
        ],
    )

    selected = docker_ssh_module.select_running_app("irrelevant")

    assert selected == "single-app"


def test_select_running_app_raises_when_none_running(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_apps",
        lambda *args, **kwargs: [
            docker_ssh_module.App(name="inactive-app", state="inactive")
        ],
    )
    with pytest.raises(ValueError, match="No running apps found"):
        docker_ssh_module.select_running_app("irrelevant")


def test_select_running_app_raises_when_multiple_running(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_apps",
        lambda *args, **kwargs: [
            docker_ssh_module.App(name="app-a", state="running"),
            docker_ssh_module.App(name="app-b", state="running"),
        ],
    )
    with pytest.raises(ValueError, match="Multiple running apps found"):
        docker_ssh_module.select_running_app("irrelevant")


def test_get_apps_raises_for_unknown_server(monkeypatch):
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {})

    with pytest.raises(ValueError, match="Unknown server"):
        docker_ssh_module.get_apps("missing-server")


def test_select_running_app_raises_value_error_for_unknown_server(monkeypatch):
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {})

    with pytest.raises(ValueError, match="Unknown server"):
        docker_ssh_module.select_running_app("missing-server")


def test_apps_outputs_table_for_all_apps(monkeypatch, capsys):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_apps",
        lambda server: [
            docker_ssh_module.App(name="alpha", state="inactive"),
            docker_ssh_module.App(name="beta", state="running"),
        ],
    )

    listed = docker_ssh_module.apps.callback(
        server="irrelevant",
    )

    output_lines = capsys.readouterr().out.strip().splitlines()
    assert listed == ["beta", "alpha"]
    assert any("app" in line and "state" in line for line in output_lines)
    assert any("beta" in line and "running" in line for line in output_lines)
    assert any("alpha" in line and "inactive" in line for line in output_lines)
    assert "\x1b[" not in "\n".join(output_lines)


def test_apps_outputs_table_when_all_inactive(monkeypatch, capsys):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_apps",
        lambda server: [
            docker_ssh_module.App(name="alpha", state="inactive"),
            docker_ssh_module.App(name="beta", state="inactive"),
        ],
    )

    listed = docker_ssh_module.apps.callback(
        server="irrelevant",
    )

    output_lines = capsys.readouterr().out.strip().splitlines()
    assert listed == ["alpha", "beta"]
    assert any("app" in line and "state" in line for line in output_lines)
    assert any("alpha" in line and "inactive" in line for line in output_lines)
    assert any("beta" in line and "inactive" in line for line in output_lines)
    assert "\x1b[" not in "\n".join(output_lines)


def _patch_yaspin(monkeypatch):
    spinner = mock.Mock()
    spinner_cm = mock.MagicMock()
    spinner_cm.__enter__.return_value = spinner
    spinner_cm.__exit__.return_value = None
    monkeypatch.setattr(docker_ssh_module, "yaspin", mock.Mock(return_value=spinner_cm))
    return spinner


def test_prepare_server_skips_install_when_docker_is_usable(monkeypatch):
    spinner = _patch_yaspin(monkeypatch)
    executor = mock.Mock()
    executor.run.side_effect = ["/usr/bin/docker\n", "usable\n"]
    executor_cls = mock.Mock(return_value=executor)
    monkeypatch.setattr(docker_ssh_module, "Executor", executor_cls)

    docker_ssh_module.prepare_server("example.com", "ubuntu")

    executor_cls.assert_called_once_with("example.com", "ubuntu")
    executor.check_sudo.assert_not_called()
    assert executor.run.call_args_list == [
        mock.call("command -v docker", raise_=False),
        mock.call("docker ps >/dev/null 2>&1 && echo usable", raise_=False),
    ]
    spinner.ok.assert_called_once_with("✔")
    spinner.fail.assert_not_called()


def test_prepare_server_installs_docker_when_missing(monkeypatch):
    spinner = _patch_yaspin(monkeypatch)
    initial_executor = mock.Mock()
    initial_executor.run.side_effect = ["", "", ""]
    refreshed_executor = mock.Mock()
    refreshed_executor.run.side_effect = ["usable\n"]
    executor_cls = mock.Mock(side_effect=[initial_executor, refreshed_executor])
    monkeypatch.setattr(docker_ssh_module, "Executor", executor_cls)

    docker_ssh_module.prepare_server("example.com", "ubuntu")

    initial_executor.check_sudo.assert_called_once_with()
    assert initial_executor.run.call_args_list == [
        mock.call("command -v docker", raise_=False),
        mock.call("wget -O - https://get.docker.com | sudo -n bash"),
        mock.call("sudo -n adduser $(id --user --name) docker"),
    ]
    assert refreshed_executor.run.call_args_list == [
        mock.call("docker ps >/dev/null 2>&1 && echo usable", raise_=False)
    ]
    assert executor_cls.call_args_list == [
        mock.call("example.com", "ubuntu"),
        mock.call("example.com", "ubuntu"),
    ]
    spinner.ok.assert_called_once_with("✔")
    spinner.fail.assert_not_called()


def test_prepare_server_repairs_permissions_for_installed_docker(monkeypatch):
    spinner = _patch_yaspin(monkeypatch)
    initial_executor = mock.Mock()
    initial_executor.run.side_effect = ["/usr/bin/docker\n", "", ""]
    refreshed_executor = mock.Mock()
    refreshed_executor.run.side_effect = ["usable\n"]
    executor_cls = mock.Mock(side_effect=[initial_executor, refreshed_executor])
    monkeypatch.setattr(docker_ssh_module, "Executor", executor_cls)

    docker_ssh_module.prepare_server("example.com", "ubuntu")

    initial_executor.check_sudo.assert_called_once_with()
    assert initial_executor.run.call_args_list == [
        mock.call("command -v docker", raise_=False),
        mock.call("docker ps >/dev/null 2>&1 && echo usable", raise_=False),
        mock.call("sudo -n adduser $(id --user --name) docker"),
    ]
    assert refreshed_executor.run.call_args_list == [
        mock.call("docker ps >/dev/null 2>&1 && echo usable", raise_=False)
    ]
    spinner.ok.assert_called_once_with("✔")
    spinner.fail.assert_not_called()


def test_prepare_server_raises_clean_error_when_docker_still_unusable(monkeypatch):
    spinner = _patch_yaspin(monkeypatch)
    initial_executor = mock.Mock()
    initial_executor.run.side_effect = ["/usr/bin/docker\n", "", ""]
    refreshed_executor = mock.Mock()
    refreshed_executor.run.side_effect = [""]
    executor_cls = mock.Mock(side_effect=[initial_executor, refreshed_executor])
    monkeypatch.setattr(docker_ssh_module, "Executor", executor_cls)

    with pytest.raises(
        click.ClickException,
        match="Docker is installed but not usable by this user",
    ):
        docker_ssh_module.prepare_server("example.com", "ubuntu")

    initial_executor.check_sudo.assert_called_once_with()
    assert initial_executor.run.call_args_list == [
        mock.call("command -v docker", raise_=False),
        mock.call("docker ps >/dev/null 2>&1 && echo usable", raise_=False),
        mock.call("sudo -n adduser $(id --user --name) docker"),
    ]
    assert refreshed_executor.run.call_args_list == [
        mock.call("docker ps >/dev/null 2>&1 && echo usable", raise_=False)
    ]
    spinner.ok.assert_not_called()
    spinner.fail.assert_called_once_with("✖")
