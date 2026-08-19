import importlib
import sys
from pathlib import Path
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


def test_invalid_policy_stops_before_docker_ssh_external_side_effects(
    tmp_path, monkeypatch
):
    (tmp_path / "deploy.toml").write_text("version = 999\nexclude = []\n")
    monkeypatch.chdir(tmp_path)
    wrapped_command = mock.Mock()
    wrapper = docker_ssh_module.build_and_push_image(wrapped_command)

    with pytest.raises(click.UsageError, match="version"):
        wrapper(
            server="test-server",
            app_name=None,
            archive_path=None,
            update=False,
            local_build=False,
            push_build=False,
        )

    wrapped_command.assert_not_called()


def test_docker_ssh_reuses_validated_source_after_destructive_preflight(
    tmp_path, monkeypatch
):
    pytest.importorskip("docker")
    events = []
    source = mock.Mock(deployment_plan=object())
    executor = mock.Mock()
    config = mock.Mock()
    config.get.side_effect = lambda key, default=None: {
        "docker_image_name": None,
        "docker_image_base_name": "base-image",
    }.get(key, default)
    config.as_dict.return_value = {"example": "value"}
    docker_client = mock.Mock()
    wrapped_command = mock.Mock(return_value="deployed")
    wrapper = docker_ssh_module.build_and_push_image(wrapped_command)

    def make_source(root):
        events.append("validate-policy")
        assert Path(root) == tmp_path
        return source

    def discover_apps(remote_executor):
        events.append("remote-discovery")
        return ["old-app"] if events.count("remote-discovery") == 1 else []

    def destroy_app(**kwargs):
        events.append("destroy-app")

    def setup(*args, **kwargs):
        events.append("assemble")
        assert kwargs["experiment_files"] is source
        return "experiment-id", tmp_path / "assembly"

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"test-server": {"host": "host"}}
    )
    with (
        mock.patch.object(
            docker_ssh_module,
            "get_experiment_files",
            side_effect=make_source,
        ),
        mock.patch.object(docker_ssh_module, "get_config", return_value=config),
        mock.patch.object(
            docker_ssh_module, "_executor_for_server", return_value=executor
        ),
        mock.patch.object(
            docker_ssh_module,
            "_discover_server_apps",
            side_effect=discover_apps,
        ),
        mock.patch.object(docker_ssh_module.click, "confirm", return_value=True),
        mock.patch.object(
            docker_ssh_module.destroy,
            "callback",
            side_effect=destroy_app,
        ),
        mock.patch.object(docker_ssh_module, "setup_experiment", side_effect=setup),
        mock.patch.object(docker_ssh_module, "ensure_remote_host_in_known_hosts"),
        mock.patch.object(docker_ssh_module, "add_server_pem_to_ssh_agent"),
        mock.patch("docker.from_env", return_value=docker_client),
        mock.patch("dallinger.docker.tools.build_image", return_value="built:image"),
    ):
        result = wrapper(
            server="test-server",
            app_name=None,
            archive_path=None,
            update=False,
            local_build=False,
            push_build=False,
        )

    assert result == "deployed"
    assert events == [
        "validate-policy",
        "remote-discovery",
        "destroy-app",
        "remote-discovery",
        "assemble",
    ]


def test_docker_ssh_local_build_pushes_without_reassembling(tmp_path, monkeypatch):
    source = mock.Mock(deployment_plan=object())
    config = mock.Mock()
    config.get.side_effect = lambda key, default=None: {
        "docker_image_name": None,
        "docker_image_base_name": "base-image",
    }.get(key, default)
    config.as_dict.return_value = {}
    wrapped_command = mock.Mock(return_value="deployed")
    wrapper = docker_ssh_module.build_and_push_image(wrapped_command)
    setup = mock.Mock(return_value=("experiment-id", tmp_path / "assembly"))
    docker_cli = importlib.import_module("dallinger.command_line.docker")
    fake_docker = mock.MagicMock()
    fake_tools = mock.Mock()
    fake_tools.build_image.return_value = "built:image"

    monkeypatch.chdir(tmp_path)
    with (
        mock.patch.object(
            docker_ssh_module, "get_experiment_files", return_value=source
        ),
        mock.patch.object(docker_ssh_module, "get_config", return_value=config),
        mock.patch.object(
            docker_ssh_module, "ensure_root_domain_ready", return_value=False
        ),
        mock.patch.object(docker_ssh_module, "setup_experiment", setup),
        mock.patch.dict(
            sys.modules,
            {"docker": fake_docker, "dallinger.docker.tools": fake_tools},
        ),
        mock.patch.object(
            docker_cli, "push_image", return_value="pushed:image"
        ) as push_image,
    ):
        result = wrapper(
            server="test-server",
            app_name=None,
            archive_path=None,
            update=False,
            local_build=True,
            push_build=False,
        )

    assert result == "deployed"
    setup.assert_called_once()
    push_image.assert_called_once_with("built:image")
    wrapped_command.assert_called_once()
    assert wrapped_command.call_args.kwargs["image_name"] == "pushed:image"
