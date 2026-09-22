import importlib
import subprocess
import sys
import uuid
from pathlib import Path
from unittest import mock

import click
import pytest

from dallinger.docker.tools import docker_tag_from_experiment_id

docker_ssh_module = importlib.import_module("dallinger.command_line.docker_ssh")


def test_monitoring_settings_default_and_override():
    assert docker_ssh_module._monitoring_settings({}) == ("experiment", "/health")
    assert docker_ssh_module._monitoring_settings(
        {
            "docker_ssh_monitoring_kind": "psynet",
            "docker_ssh_monitoring_path": "/health",
        }
    ) == ("psynet", "/health")


def _mock_executor(manifest_dump="", marker_paths=""):
    executor = mock.Mock()

    def run(cmd, raise_=True):
        if "docker ps" in cmd:
            return "beta\n"
        if "state/hibernating" in cmd:
            return marker_paths
        if "printf" in cmd and "===" in cmd:
            return manifest_dump
        return (
            "alpha\n"
            "/home/test/dallinger/beta/docker-compose.yml\n"
            "/home/test/dallinger/beta/deployment.json\n"
        )

    executor.run.side_effect = run
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


def test_select_running_app_returns_lone_hibernating_app(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_apps",
        lambda *args, **kwargs: [
            docker_ssh_module.App(name="asleep", state="hibernating")
        ],
    )

    assert docker_ssh_module.select_running_app("irrelevant") == "asleep"


def test_classic_update_refuses_existing_cloudflare_app(capsys):
    with pytest.raises(click.Abort):
        docker_ssh_module._abort_classic_overwrite_of_cloudflare(
            docker_ssh_module.INGRESS_CLOUDFLARE, "demo"
        )
    printed = capsys.readouterr().out
    assert "{END}" not in printed
    assert "classic Caddy ingress." in printed
    docker_ssh_module._abort_classic_overwrite_of_cloudflare(
        docker_ssh_module.INGRESS_CLASSIC, "demo"
    )


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


def test_get_apps_uses_manifest_ingress_and_origin():
    dump = (
        "=== beta ===\n"
        '{"schema_version": 1, "app": "beta", "server": "lab", '
        '"ingress": "cloudflare", '
        '"public_origin": "https://beta.science-of-music.org", '
        '"monitoring": {"kind": "psynet", "path": "/health", "enabled": true}, '
        '"database": {"layout": "app"}, "cloudflare": {"tunnel_id": "abc"}, '
        '"hibernation": {"state": "hibernating", "idle_enabled": true, "minutes": 15}}\n'
    )
    executor = _mock_executor(
        manifest_dump=dump,
        marker_paths="/home/test/dallinger/beta/state/hibernating\n",
    )
    server_info = {"host": "example.com", "user": "ubuntu"}
    with (
        mock.patch.object(
            docker_ssh_module, "_resolve_server_info", return_value=server_info
        ),
        mock.patch.object(docker_ssh_module, "_build_executor", return_value=executor),
    ):
        apps = docker_ssh_module.get_apps("irrelevant")

    by_name = {app.name: app for app in apps}
    assert by_name["alpha"].ingress == "classic"
    assert by_name["alpha"].public_origin is None
    assert by_name["beta"].ingress == "cloudflare"
    assert by_name["beta"].public_origin == "https://beta.science-of-music.org"
    assert by_name["beta"].database_layout == "app"
    assert by_name["beta"].hibernation_state == "hibernating"
    assert by_name["beta"].state == "hibernating"


def test_get_apps_ignores_stale_hibernating_manifest_without_markers():
    dump = (
        "=== beta ===\n"
        '{"schema_version": 1, "app": "beta", "server": "lab", '
        '"ingress": "classic", '
        '"public_origin": "https://beta.example.org", '
        '"monitoring": {"kind": "experiment", "path": "/health", "enabled": true}, '
        '"database": {"layout": "shared"}, "cloudflare": {}, '
        '"hibernation": {"state": "hibernating", "idle_enabled": false, "minutes": 30}}\n'
    )
    executor = _mock_executor(manifest_dump=dump)
    server_info = {"host": "example.com", "user": "ubuntu"}
    with (
        mock.patch.object(
            docker_ssh_module, "_resolve_server_info", return_value=server_info
        ),
        mock.patch.object(docker_ssh_module, "_build_executor", return_value=executor),
    ):
        apps = docker_ssh_module.get_apps("irrelevant")

    by_name = {app.name: app for app in apps}
    assert by_name["beta"].hibernation_state == "awake"
    assert by_name["beta"].state == "running"


def test_cloudflare_settings_ignore_classic_dns_host():
    server = {
        "cloudflare_account_id": "acct",
        "cloudflare_zone_id": "zone",
        "cloudflare_dns_zone": "science-of-music.org",
    }
    config = mock.Mock()
    config.get.return_value = ""
    settings = docker_ssh_module._cloudflare_settings(server, config)
    assert settings["dns_zone"] == "science-of-music.org"


def test_upload_app_manifest_writes_deployment_json():
    sftp = mock.Mock()
    manifest = docker_ssh_module.DeploymentManifest.classic(
        app="consonance",
        server="musix",
        public_origin="https://consonance.science-of-music.org",
    )
    docker_ssh_module._upload_app_manifest(sftp, manifest)
    assert sftp.putfo.call_args.args[1] == "dallinger/consonance/deployment.json"
    uploaded = sftp.putfo.call_args.args[0].getvalue().decode()
    assert '"token"' not in uploaded
    assert "consonance.science-of-music.org" in uploaded


def test_discover_server_apps_includes_manifest_only_names():
    executor = mock.Mock()
    executor.run.return_value = (
        "/home/test/dallinger/tunnel-app/deployment.json\npsynet-01\n"
    )
    assert docker_ssh_module._discover_server_apps(executor) == [
        "psynet-01",
        "tunnel-app",
    ]


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
    assert any("ingress" in line and "origin" in line for line in output_lines)
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
    assert any("ingress" in line and "origin" in line for line in output_lines)
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
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
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
        mock.patch(
            "dallinger.docker.tools.build_image", return_value="built:image"
        ) as build_image,
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
    assert build_image.call_args.kwargs["image_tag"] == (
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )


def test_docker_ssh_local_build_pushes_without_reassembling(tmp_path, monkeypatch):
    source = mock.Mock(deployment_plan=object())
    config = mock.Mock()
    config.get.side_effect = lambda key, default=None: {
        "docker_image_name": None,
        "docker_image_base_name": "base-image",
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    }.get(key, default)
    config.as_dict.return_value = {}
    wrapped_command = mock.Mock(return_value="deployed")
    wrapper = docker_ssh_module.build_and_push_image(wrapped_command)
    setup = mock.Mock(return_value=("experiment-id", tmp_path / "assembly"))
    docker_cli = importlib.import_module("dallinger.command_line.docker")
    fake_docker = mock.MagicMock()
    fake_tools = mock.Mock()
    fake_tools.build_image.return_value = "built:image"
    fake_tools.docker_tag_from_experiment_id = docker_tag_from_experiment_id

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"test-server": {"host": "host"}},
    )
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
    assert fake_tools.build_image.call_args.kwargs["image_tag"] == (
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )


def test_experiment_image_from_compose_reads_web_not_infra_images():
    yml = docker_ssh_module.get_docker_compose_yml(
        {
            "num_dynos_worker": 2,
            "clock_on": True,
            "docker_worker_cpu_shares": 1024,
            "docker_image_name": "ghcr.io/org/exp:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        },
        "my-app",
        "ghcr.io/org/exp:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "pw",
    )
    parsed = docker_ssh_module.experiment_image_from_compose(yml)
    assert parsed == "ghcr.io/org/exp:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert parsed not in {
        "redis",
        "postgres:12",
        "caddy:2",
        "docker.io/bitnamilegacy/pgbouncer:1.24.1",
        "amir20/dozzle:v10.0.2",
    }


def test_remove_experiment_image_runs_docker_rmi_without_force():
    executor = mock.Mock()
    docker_ssh_module.remove_experiment_image(executor, "registry/exp:old-uid")
    executor.run.assert_called_once_with(
        "docker rmi registry/exp:old-uid", raise_=False
    )
    assert "--force" not in executor.run.call_args[0][0]


def test_remove_unshared_skips_rmi_when_another_app_pins_the_image():
    executor = mock.Mock()
    executor.run.return_value = "/home/ubuntu/dallinger/otherapp/docker-compose.yml\n"
    docker_ssh_module.remove_unshared_experiment_image(
        executor, "registry/exp:shared", except_app="myapp"
    )
    commands = [call.args[0] for call in executor.run.call_args_list]
    assert any(cmd.startswith("grep -xF -l") for cmd in commands)
    assert not any(cmd.startswith("docker rmi") for cmd in commands)


def _patch_destroy_executor(monkeypatch, run):
    executor = mock.Mock()
    executor.run.side_effect = run
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"test-server": {"host": "example.com", "user": "ubuntu"}},
    )
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *args, **kwargs: executor)
    return executor


def test_destroy_removes_unique_image_after_down_not_infra(monkeypatch):
    compose_yml = docker_ssh_module.get_docker_compose_yml(
        {},
        "myapp",
        "registry/exp:old-uid",
        "pw",
    )
    commands = []

    def run(cmd, raise_=True):
        commands.append(cmd)
        if cmd.startswith("test -f") and "caddy.d" in cmd:
            return ""
        if cmd.startswith("test -f") and "docker-compose.yml" in cmd:
            return "Yes"
        if cmd == "cat ~/dallinger/myapp/docker-compose.yml":
            return compose_yml
        if cmd == "cat ~/dallinger/Caddyfile":
            return "https://example.com {\n    reverse_proxy other_web:5000\n}\n"
        if cmd.startswith("grep -xF -l"):
            return "/home/ubuntu/dallinger/myapp/docker-compose.yml\n"
        return ""

    _patch_destroy_executor(monkeypatch, run)
    docker_ssh_module.destroy.callback(server="test-server", app="myapp")

    down = "docker compose -f ~/dallinger/myapp/docker-compose.yml down"
    rmi = "docker rmi registry/exp:old-uid"
    rm_tree = "rm -rf ~/dallinger/myapp/"
    assert commands.index(down) < commands.index(rmi) < commands.index(rm_tree)
    rmi_commands = [cmd for cmd in commands if cmd.startswith("docker rmi")]
    assert rmi_commands == [rmi]
    for forbidden in (
        "redis",
        "postgres:12",
        "caddy:2",
        "pgbouncer",
        "amir20/dozzle",
    ):
        assert not any(forbidden in cmd for cmd in rmi_commands)


def test_resolve_ingress_uses_server_default():
    assert (
        docker_ssh_module._resolve_ingress({"default_ingress": "cloudflare"})
        == "cloudflare"
    )
    assert docker_ssh_module._resolve_ingress({}, ingress="classic") == "classic"
    assert docker_ssh_module._resolve_ingress({}) == "classic"


def test_cloudflare_restore_runs_before_compose_up(monkeypatch):
    order = []
    executor = mock.Mock()

    def run(cmd, raise_=True):
        order.append(cmd)
        return ""

    executor.run.side_effect = run
    monkeypatch.setattr(
        docker_ssh_module,
        "_restore_experiment_archive",
        lambda *_args: order.append("restore"),
    )
    monkeypatch.setattr(
        docker_ssh_module,
        "_repark_parked_app",
        lambda *_args: order.append("repark"),
    )
    docker_ssh_module._bring_up_app_containers(
        executor,
        {},
        "dlgr-abcd1234",
        "/tmp/export.zip",
        True,
        restore=True,
    )
    restore_at = order.index("restore")
    up_at = next(index for index, item in enumerate(order) if "up -d" in item)
    assert restore_at < up_at
    assert "repark" not in order


def test_classic_bring_up_does_not_restore_twice(monkeypatch):
    executor = mock.Mock()
    executor.run.return_value = ""
    monkeypatch.setattr(
        docker_ssh_module,
        "_restore_experiment_archive",
        mock.Mock(side_effect=AssertionError("classic already restored")),
    )
    monkeypatch.setattr(docker_ssh_module, "_repark_parked_app", lambda *_args: None)
    docker_ssh_module._bring_up_app_containers(
        executor,
        {},
        "dlgr-abcd1234",
        "/tmp/export.zip",
        True,
        restore=False,
    )
    commands = [call.args[0] for call in executor.run.call_args_list]
    assert any("up -d" in command for command in commands)
    assert not any("initdb" in command for command in commands)


def test_bring_up_snapshots_parked_state_before_compose_up(monkeypatch):
    order = []
    executor = mock.Mock()

    def run(cmd, raise_=True):
        order.append(cmd)
        if cmd.startswith("test -e"):
            return "Yes"
        return ""

    executor.run.side_effect = run
    monkeypatch.setattr(
        docker_ssh_module,
        "_repark_parked_app",
        lambda *_args: order.append("repark"),
    )
    docker_ssh_module._bring_up_app_containers(
        executor,
        {},
        "dlgr-abcd1234",
        None,
        True,
        restore=False,
    )
    probe_at = next(
        index for index, item in enumerate(order) if item.startswith("test -e")
    )
    up_at = next(index for index, item in enumerate(order) if "up -d" in item)
    assert probe_at < up_at
    assert order[-1] == "repark"


def test_bring_up_leaves_an_awake_app_running(monkeypatch):
    reparked = []
    executor = mock.Mock()
    executor.run.return_value = ""
    monkeypatch.setattr(
        docker_ssh_module,
        "_repark_parked_app",
        lambda *_args: reparked.append(True),
    )
    docker_ssh_module._bring_up_app_containers(
        executor,
        {},
        "dlgr-abcd1234",
        None,
        True,
        restore=False,
    )
    assert reparked == []


def test_repark_uses_the_controller_without_dumping_logs():
    executor = mock.Mock()

    def run(cmd, raise_=True):
        assert raise_ is False
        if "client hibernate" in cmd:
            return docker_ssh_module._REMOTE_OK
        return ""

    executor.run.side_effect = run
    docker_ssh_module._repark_parked_app(executor, "dlgr-abcd1234")
    commands = [call.args[0] for call in executor.run.call_args_list]
    assert len(commands) == 1
    assert "dallinger_hibernation client hibernate" in commands[0]
    assert "compose stop" not in commands[0]


def test_repark_stops_services_when_controller_stays_down(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        docker_ssh_module.time, "sleep", lambda seconds: sleeps.append(seconds)
    )
    executor = mock.Mock()

    def run(cmd, raise_=True):
        assert raise_ is False
        return ""

    executor.run.side_effect = run
    docker_ssh_module._repark_parked_app(executor, "dlgr-abcd1234")
    commands = [call.args[0] for call in executor.run.call_args_list]
    assert sleeps == [1, 1, 1, 1]
    assert sum("client hibernate" in command for command in commands) == 5
    fallback = commands[-1]
    assert (
        "docker compose -f ~/dallinger/dlgr-abcd1234/docker-compose.yml stop"
        in fallback
    )
    assert "touch ~/dallinger/dlgr-abcd1234/state/hibernating" in fallback
    assert "rm -f ~/dallinger/dlgr-abcd1234/state/waking" in fallback
    assert "worker_" in fallback
    assert "frontdoor" not in fallback
    assert "cloudflared" not in fallback


def test_cloudflare_deploy_skips_root_domain_preflight(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"lab": {"host": "lab.example", "default_ingress": "cloudflare"}},
    )
    assert not docker_ssh_module._root_domain_preflight_required(
        "lab", None, None, None
    )
    assert not docker_ssh_module._root_domain_preflight_required(
        "lab", None, "/tmp/export.zip", None
    )
    assert not docker_ssh_module._root_domain_preflight_required(
        "lab", None, None, "cloudflare"
    )
    assert docker_ssh_module._root_domain_preflight_required(
        "lab", None, None, "classic"
    )
    assert not docker_ssh_module._root_domain_preflight_required(
        "lab", "dlgr-abcd1234", None, "classic"
    )


def test_destroy_cloudflare_skips_caddy_and_removes_volumes(monkeypatch):
    dump = (
        "=== myapp ===\n"
        '{"schema_version": 1, "app": "myapp", "server": "test-server", '
        '"ingress": "cloudflare", '
        '"public_origin": "https://myapp.science-of-music.org", '
        '"monitoring": {"kind": "experiment", "path": "/health", "enabled": true}, '
        '"database": {"layout": "app"}, '
        '"cloudflare": {"tunnel_id": "tun", "dns_record_id": "dns", '
        '"hostname": "myapp.science-of-music.org", "dns_zone": "science-of-music.org"}, '
        '"hibernation": {"state": "awake", "idle_enabled": false, "minutes": 60}}\n'
    )
    compose_yml = docker_ssh_module.get_docker_compose_yml(
        {},
        "myapp",
        "registry/exp:old-uid",
        "pw",
        ingress="cloudflare",
    )
    commands = []

    def run(cmd, raise_=True):
        commands.append(cmd)
        if cmd.startswith("test -f") and "docker-compose.yml" in cmd:
            return "Yes"
        if cmd.startswith("test -f") and "deployment.json" in cmd:
            return "Yes"
        if "printf" in cmd and "===" in cmd:
            return dump
        if cmd == "cat ~/dallinger/myapp/docker-compose.yml":
            return compose_yml
        if cmd.startswith("grep -xF -l"):
            return "/home/ubuntu/dallinger/myapp/docker-compose.yml\n"
        return ""

    executor = _patch_destroy_executor(monkeypatch, run)
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {
            "test-server": {
                "host": "example.com",
                "user": "ubuntu",
                "cloudflare_account_id": "acct",
                "cloudflare_zone_id": "zone",
                "cloudflare_dns_zone": "science-of-music.org",
            }
        },
    )
    deleted = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "delete_experiment_tunnel", deleted)
    monkeypatch.setattr(docker_ssh_module, "load_api_token", lambda config: "tok")
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load=False: mock.Mock())

    docker_ssh_module.destroy.callback(server="test-server", app="myapp")

    executor.reload_caddy.assert_not_called()
    assert not any(cmd == "cat ~/dallinger/Caddyfile" for cmd in commands)
    assert any(cmd.endswith("down -v") for cmd in commands)
    deleted.assert_called_once()
    assert deleted.call_args.kwargs["app"] == "myapp"
    assert deleted.call_args.kwargs["tunnel_id"] == "tun"


def test_gc_lists_orphan_tunnels_without_deleting(monkeypatch, capsys):
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {
            "test-server": {
                "host": "example.com",
                "user": "ubuntu",
                "cloudflare_account_id": "acct",
                "cloudflare_zone_id": "zone",
                "cloudflare_dns_zone": "science-of-music.org",
            }
        },
    )
    monkeypatch.setattr(
        docker_ssh_module,
        "get_apps",
        lambda server: [docker_ssh_module.App(name="kept", state="running")],
    )
    monkeypatch.setattr(docker_ssh_module, "load_api_token", lambda config: "tok")
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load=False: mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module,
        "list_prefixed_tunnels",
        lambda account_id, token: [
            {"id": "1", "name": "dallinger-kept"},
            {"id": "2", "name": "dallinger-gone"},
        ],
    )
    deleted = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "delete_experiment_tunnel", deleted)

    orphans = docker_ssh_module.gc.callback(
        server="test-server", apply=False, confirm_no_other_hosts=False
    )

    assert orphans == ["gone"]
    deleted.assert_not_called()
    output = capsys.readouterr().out
    assert "dallinger-gone" in output
    assert "--confirm-no-other-hosts" in output


def test_gc_apply_aborts_without_confirming_no_other_hosts(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {
            "test-server": {
                "host": "example.com",
                "user": "ubuntu",
                "cloudflare_account_id": "acct",
                "cloudflare_zone_id": "zone",
                "cloudflare_dns_zone": "science-of-music.org",
            }
        },
    )
    monkeypatch.setattr(docker_ssh_module, "get_apps", lambda server: [])
    monkeypatch.setattr(docker_ssh_module, "load_api_token", lambda config: "tok")
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load=False: mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module,
        "list_prefixed_tunnels",
        lambda account_id, token: [{"id": "2", "name": "dallinger-gone"}],
    )
    deleted = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "delete_experiment_tunnel", deleted)

    with pytest.raises(click.Abort):
        docker_ssh_module.gc.callback(
            server="test-server", apply=True, confirm_no_other_hosts=False
        )
    deleted.assert_not_called()


def test_gc_apply_deletes_when_no_other_hosts_confirmed(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {
            "test-server": {
                "host": "example.com",
                "user": "ubuntu",
                "cloudflare_account_id": "acct",
                "cloudflare_zone_id": "zone",
                "cloudflare_dns_zone": "science-of-music.org",
            }
        },
    )
    monkeypatch.setattr(docker_ssh_module, "get_apps", lambda server: [])
    monkeypatch.setattr(docker_ssh_module, "load_api_token", lambda config: "tok")
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load=False: mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module,
        "list_prefixed_tunnels",
        lambda account_id, token: [{"id": "2", "name": "dallinger-gone"}],
    )
    deleted = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "delete_experiment_tunnel", deleted)

    orphans = docker_ssh_module.gc.callback(
        server="test-server", apply=True, confirm_no_other_hosts=True
    )

    assert orphans == ["gone"]
    deleted.assert_called_once()


def test_compose_environment_strips_cloudflare_api_token():
    class Config:
        def as_dict(self, include_sensitive=False):
            return {
                "aws_access_key_id": "id",
                "aws_secret_access_key": "secret",
                "cloudflare_api_token": "must-not-leak",
                "host": "0.0.0.0",
                "aws_region": "us-east-1",
                "auto_recruit": False,
            }

        def get(self, key, default=None):
            return None

        def __getitem__(self, key):
            return self.as_dict()[key]

    env = docker_ssh_module._compose_environment(
        Config(),
        {"cloudflare_api_token": "from-cli", "host": "smuggled"},
        "live",
        "uuid",
        "image:tag",
    )
    assert "cloudflare_api_token" not in env
    assert "from-cli" not in env.values()
    assert env["AWS_ACCESS_KEY_ID"] == "id"
    assert "host" not in env


def test_remote_postgres_uses_app_container_when_present(monkeypatch):
    executor = mock.Mock()

    def run(cmd, raise_=True):
        if "myapp-postgresql-1" in cmd and "IPAddress" in cmd:
            return "10.0.0.9\n"
        if "myapp-postgresql-1" in cmd and "Env" in cmd:
            return "POSTGRES_USER=myapp\nPOSTGRES_PASSWORD=s3cret\nPOSTGRES_DB=myapp\n"
        return ""

    executor.run.side_effect = run
    tunnel = mock.Mock(local_bind_port=65432)
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *a, **k: executor)
    monkeypatch.setattr(
        docker_ssh_module, "get_server_pem_path", lambda: "/tmp/key.pem"
    )
    fake_sshtunnel = mock.Mock()
    fake_sshtunnel.SSHTunnelForwarder.return_value = tunnel
    monkeypatch.setitem(sys.modules, "sshtunnel", fake_sshtunnel)

    with docker_ssh_module.remote_postgres(
        {"host": "example.com", "user": "ubuntu"}, "myapp"
    ) as uri:
        assert uri == "postgresql://myapp:s3cret@localhost:65432/myapp"
    tunnel.start.assert_called_once()
    tunnel.stop.assert_called_once()


class _LocalDockerExecutor:
    def run(self, cmd, raise_=True):
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, check=False
        )
        if raise_ and result.returncode != 0:
            raise RuntimeError(result.stderr)
        return result.stdout


def _docker_image_exists(tag):
    return (
        subprocess.run(
            ["docker", "image", "inspect", tag],
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def _import_empty_image(tag):
    empty_tar = subprocess.check_output(["tar", "-c", "-T", "/dev/null"])
    subprocess.run(
        ["docker", "import", "--change", 'CMD ["true"]', "-", tag],
        input=empty_tar,
        check=True,
    )


@pytest.mark.docker
def test_real_docker_rmi_removes_unused_tag_and_keeps_in_use_and_prefix_tags():
    suffix = uuid.uuid4().hex[:12]
    unused = f"dallinger-cleanup-test-{suffix}:unused"
    in_use = f"dallinger-cleanup-test-{suffix}:in-use"
    prefix_short = f"dallinger-cleanup-test-{suffix}:abc"
    prefix_long = f"dallinger-cleanup-test-{suffix}:abcd"
    container = f"dallinger-cleanup-test-{suffix}"
    executor = _LocalDockerExecutor()
    created = []
    try:
        for tag in (unused, in_use, prefix_short, prefix_long):
            _import_empty_image(tag)
            created.append(tag)
            assert _docker_image_exists(tag)

        subprocess.run(
            ["docker", "create", "--name", container, in_use],
            check=True,
            capture_output=True,
        )

        docker_ssh_module.remove_experiment_image(executor, unused)
        docker_ssh_module.remove_experiment_image(executor, in_use)
        docker_ssh_module.remove_experiment_image(executor, prefix_short)

        assert not _docker_image_exists(unused)
        assert _docker_image_exists(in_use)
        assert not _docker_image_exists(prefix_short)
        assert _docker_image_exists(prefix_long)
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container], capture_output=True, check=False
        )
        for tag in created:
            subprocess.run(
                ["docker", "rmi", "-f", tag], capture_output=True, check=False
            )


def test_write_experiment_compose_env_chowns_data_dirs():
    executor = mock.Mock()
    docker_ssh_module._write_experiment_compose_env(
        executor,
        "consonance",
        "${HOME}/psynet-data/assets:/psynet-data/assets",
    )
    cmd = executor.run.call_args.args[0]
    assert "UID=%s" in cmd
    assert "DOCKER_GID=%s" in cmd
    assert "chown -R" in cmd
    assert "sudo -n chown" in cmd
    assert "alpine:3.20" in cmd
    assert "dallinger-data/$app" in cmd
    assert "dallinger/$app/state" in cmd
    assert "$HOME/psynet-data/assets" in cmd
    assert "consonance" in cmd


def test_remote_bind_mount_dirs_skips_relative_volumes():
    dirs = docker_ssh_module._remote_bind_mount_dirs(
        "./dallinger.log:/experiment/dallinger.log,${HOME}/psynet-data/assets:/psynet-data/assets",
        "consonance",
    )
    assert '"$HOME/dallinger-data/$app"' in dirs
    assert '"$HOME/psynet-data/assets"' in dirs
    assert not any("./" in item for item in dirs)


def test_awaken_app_optional_when_compose_missing(monkeypatch):
    executor = mock.Mock()
    executor.run.return_value = ""
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"s": {"host": "example.com", "user": "ubuntu"}},
    )
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *a, **k: executor)
    assert docker_ssh_module.awaken_app("s", "demo", required=False) is False
    with pytest.raises(click.Abort):
        docker_ssh_module.awaken_app("s", "demo", required=True)


def test_awaken_app_optional_when_controller_exec_fails(monkeypatch):
    executor = mock.Mock()

    def run(cmd, raise_=True):
        if "test -f" in cmd:
            return "Yes"
        if cmd.startswith("cat "):
            return "controller:\n"
        if raise_:
            raise docker_ssh_module.ExecuteException("exec failed")
        return ""

    executor.run.side_effect = run
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"s": {"host": "example.com", "user": "ubuntu"}},
    )
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *a, **k: executor)
    assert docker_ssh_module.awaken_app("s", "demo", required=False) is False


def test_remote_postgres_prefers_pinned_container_name(monkeypatch):
    executor = mock.Mock()

    def run(cmd, raise_=True):
        if "myapp_postgresql" in cmd and "IPAddress" in cmd:
            return "10.0.0.8\n"
        if "myapp_postgresql" in cmd and "Env" in cmd:
            return "POSTGRES_USER=myapp\nPOSTGRES_PASSWORD=s3cret\nPOSTGRES_DB=myapp\n"
        if "myapp-postgresql-1" in cmd or "dallinger-postgresql-1" in cmd:
            raise AssertionError(f"unexpected fallback: {cmd}")
        return ""

    executor.run.side_effect = run
    tunnel = mock.Mock(local_bind_port=65432)
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *a, **k: executor)
    monkeypatch.setattr(
        docker_ssh_module, "get_server_pem_path", lambda: "/tmp/key.pem"
    )
    fake_sshtunnel = mock.Mock()
    fake_sshtunnel.SSHTunnelForwarder.return_value = tunnel
    monkeypatch.setitem(sys.modules, "sshtunnel", fake_sshtunnel)

    with docker_ssh_module.remote_postgres(
        {"host": "example.com", "user": "ubuntu"}, "myapp"
    ) as uri:
        assert uri == "postgresql://myapp:s3cret@localhost:65432/myapp"


def test_remote_postgres_does_not_fall_back_when_app_db_is_stopped(monkeypatch):
    executor = mock.Mock()

    def run(cmd, raise_=True):
        if "myapp_postgresql" in cmd and ".Id" in cmd:
            return "abc123\n"
        if "dallinger-postgresql-1" in cmd and "IPAddress" in cmd:
            return "10.0.0.1\n"
        return ""

    executor.run.side_effect = run
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *a, **k: executor)
    monkeypatch.setattr(
        docker_ssh_module, "get_server_pem_path", lambda: "/tmp/key.pem"
    )
    with pytest.raises(docker_ssh_module.ExecuteException, match="not running"):
        with docker_ssh_module.remote_postgres(
            {"host": "example.com", "user": "ubuntu"}, "myapp"
        ):
            pass
