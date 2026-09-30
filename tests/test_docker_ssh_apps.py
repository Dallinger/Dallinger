import importlib
import os
import subprocess
import sys
import uuid
from pathlib import Path
from unittest import mock

import click
import pytest

from dallinger.docker.tools import docker_tag_from_experiment_id

docker_ssh_module = importlib.import_module("dallinger.command_line.docker_ssh")


def test_docker_host_uri_omits_at_sign_usernames(capsys):
    assert (
        docker_ssh_module.docker_host_uri("rr-pc01.example", user="pmch2@cam.ac.uk")
        == "ssh://rr-pc01.example"
    )
    assert "User pmch2@cam.ac.uk" in capsys.readouterr().out
    assert (
        docker_ssh_module.docker_host_uri("musix.example", user="pmch2", port=2222)
        == "ssh://pmch2@musix.example:2222"
    )


class FakeExecutor:
    """Answer remote commands by the first matching substring, in any order."""

    def __init__(self, replies):
        self.replies = replies
        self.commands = []

    def run(self, cmd, raise_=True):
        self.commands.append(cmd)
        for pattern, reply in self.replies.items():
            if pattern in cmd:
                return reply
        return ""


# ``chown`` is in /usr/sbin on macOS.
BASE_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"


class LocalExecutor:
    """Run remote shell snippets with bash, using ``home`` as ``$HOME``.

    ``bin_dir`` goes first on ``PATH``, for fake ``docker`` or ``stat``.
    """

    def __init__(self, home, bin_dir=None):
        self.home = home
        self.path = f"{bin_dir}:{BASE_PATH}" if bin_dir else BASE_PATH

    def run(self, cmd, raise_=True):
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            env={"HOME": str(self.home), "PATH": self.path},
        )
        if raise_ and result.returncode:
            raise docker_ssh_module.ExecuteException(result.stderr)
        return result.stdout


def _mock_executor(manifest_lines=""):
    return FakeExecutor(
        {
            "caddy.d": "alpha\n/home/test/dallinger/beta/docker-compose.yml\n",
            "docker ps": "beta\n",
            "deployment.json": manifest_lines,
        }
    )


def test_load_remote_manifests_reads_existing_files(tmp_path):
    manifest = docker_ssh_module.DeploymentManifest(
        app="beta",
        server="lab",
        public_origin="https://beta.example",
        ingress="cloudflare",
    )
    (tmp_path / "dallinger" / "beta").mkdir(parents=True)
    (tmp_path / "dallinger" / "beta" / "deployment.json").write_text(manifest.to_json())
    loaded = docker_ssh_module._load_remote_manifests(
        LocalExecutor(tmp_path), ["alpha", "beta", "beta~", "has space"]
    )
    assert loaded == {"beta": manifest}


def test_resolve_ingress_uses_server_default():
    assert (
        docker_ssh_module._resolve_ingress({"default_ingress": "cloudflare"})
        == "cloudflare"
    )
    assert docker_ssh_module._resolve_ingress({}, ingress="classic") == "classic"
    assert docker_ssh_module._resolve_ingress({}) == "classic"


def test_cloudflare_deploy_skips_root_domain_preflight(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"lab": {"host": "lab.example", "default_ingress": "cloudflare"}},
    )
    assert not docker_ssh_module._root_domain_preflight_required(
        "lab", None, None, None
    )
    assert docker_ssh_module._root_domain_preflight_required(
        "lab", None, None, "classic"
    )
    assert not docker_ssh_module._root_domain_preflight_required(
        "lab", "dlgr-abcd1234", None, "classic"
    )


def _cloudflare_destroy(monkeypatch, removed, cloudflare=None):
    manifest = docker_ssh_module.DeploymentManifest(
        app="myapp",
        server="test-server",
        public_origin="https://myapp.science-of-music.org",
        ingress="cloudflare",
        cloudflare=cloudflare
        or {"tunnel_id": "tun", "dns_zone": "science-of-music.org"},
    )
    order = []

    def run(cmd, raise_=True):
        if cmd.startswith("test -f") and "docker-compose.yml" in cmd:
            return "Yes"
        if cmd.startswith("for app in"):
            return "myapp\t" + manifest.to_json().replace("\n", "") + "\n"
        for marker, name in (
            ("stop cloudflared", "stop"),
            ("down -v", "down"),
            ("rm -rf", "rm"),
        ):
            if marker in cmd:
                order.append(name)
        return ""

    def delete(**kwargs):
        order.append(("delete", kwargs["app"], kwargs["account_id"]))
        order.append(("own", kwargs["own_tunnel_id"]))
        return removed

    _patch_destroy_executor(monkeypatch, run)
    monkeypatch.setattr(docker_ssh_module, "delete_experiment_tunnel", delete)
    monkeypatch.setattr(docker_ssh_module, "load_api_token", lambda config: "token")
    monkeypatch.setattr(
        docker_ssh_module,
        "get_config",
        lambda **kwargs: {"cloudflare_account_id": "acct", "cloudflare_zone_id": "z"},
    )
    return order


def test_destroy_cloudflare_stops_connector_before_deleting_the_tunnel(monkeypatch):
    order = _cloudflare_destroy(monkeypatch, removed=True)
    docker_ssh_module.destroy.callback(server="test-server", app="myapp")
    assert order == ["stop", ("delete", "myapp", "acct"), ("own", "tun"), "down", "rm"]


def test_destroy_uses_the_cloudflare_ids_recorded_at_deploy(monkeypatch):
    recorded = {
        "account_id": "deploy-acct",
        "zone_id": "deploy-zone",
        "dns_zone": "x.org",
    }
    order = _cloudflare_destroy(monkeypatch, removed=True, cloudflare=recorded)
    docker_ssh_module.destroy.callback(server="test-server", app="myapp")
    assert ("delete", "myapp", "deploy-acct") in order


def test_destroy_keeps_the_app_when_cloudflare_cleanup_fails(monkeypatch):
    order = _cloudflare_destroy(monkeypatch, removed=False)
    with pytest.raises(click.Abort):
        docker_ssh_module.destroy.callback(server="test-server", app="myapp")
    assert order == ["stop", ("delete", "myapp", "acct"), ("own", "tun")]


def test_monitoring_settings_default_and_override():
    assert docker_ssh_module._monitoring_settings({}) == ("experiment", "/health")
    assert docker_ssh_module._monitoring_settings(
        {
            "docker_ssh_monitoring_kind": "psynet",
            "docker_ssh_monitoring_path": "/health",
        }
    ) == ("psynet", "/health")


def test_upload_app_manifest_writes_deployment_json():
    sftp = mock.Mock()
    manifest = docker_ssh_module.DeploymentManifest(
        app="consonance",
        server="musix",
        public_origin="https://consonance.science-of-music.org",
    )
    docker_ssh_module._upload_app_manifest(sftp, manifest)
    assert sftp.putfo.call_args.args[1] == "dallinger/consonance/deployment.json"
    uploaded = sftp.putfo.call_args.args[0].getvalue().decode()
    assert '"token"' not in uploaded
    assert "consonance.science-of-music.org" in uploaded


def test_get_apps_uses_manifest_ingress_and_origin():
    manifest = docker_ssh_module.DeploymentManifest(
        app="beta",
        server="lab",
        public_origin="https://beta.example.org",
        ingress="cloudflare",
    )
    executor = _mock_executor("beta\t" + manifest.to_json().replace("\n", "") + "\n")
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
    assert by_name["beta"].public_origin == "https://beta.example.org"


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


def test_update_refuses_to_switch_ingress():
    manifest = docker_ssh_module.DeploymentManifest(
        app="myapp",
        server="s",
        public_origin="https://myapp.example",
        ingress="cloudflare",
    )
    executor = mock.Mock()
    executor.run.side_effect = lambda cmd, raise_=True: (
        "myapp\t" + manifest.to_json().replace("\n", "")
        if cmd.startswith("for app in")
        else "docker-compose.yml"
    )
    with pytest.raises(click.Abort):
        docker_ssh_module._check_app_slot(executor, "myapp", True, "classic")
    docker_ssh_module._check_app_slot(executor, "myapp", True, "cloudflare")


def test_app_stack_keeps_secrets_out_of_the_compose_file():
    sftp = mock.Mock()
    stack_executor = FakeExecutor({})
    docker_ssh_module._upload_app_stack(
        sftp,
        stack_executor,
        {},
        app="myapp",
        server="s",
        public_origin="https://myapp.example",
        image_name="img",
        ingress="cloudflare",
        secrets={"POSTGRES_PASSWORD": "s3cret"},
    )
    uploads = {
        call.args[1]: call.args[0].getvalue().decode()
        for call in sftp.putfo.call_args_list
    }
    assert "s3cret" not in uploads["dallinger/myapp/docker-compose.yml"]
    assert "${POSTGRES_PASSWORD}" in uploads["dallinger/myapp/docker-compose.yml"]
    assert uploads["dallinger/myapp/.env"] == "POSTGRES_PASSWORD=s3cret\n"
    assert any(
        "umask 077" in cmd and "dallinger/myapp/.env" in cmd
        for cmd in stack_executor.commands
    )
    executor = mock.Mock()
    executor.run.return_value = "UID=1\nPOSTGRES_PASSWORD=s3cret\n"
    assert (
        docker_ssh_module._existing_app_secret(executor, "myapp", "POSTGRES_PASSWORD")
        == "s3cret"
    )


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


def test_remote_postgres_prefers_pinned_container_name(monkeypatch):
    executor = mock.Mock()

    def run(cmd, raise_=True):
        if "myapp_postgresql" in cmd and "IPAddress" in cmd:
            return "10.0.0.8\n"
        if "myapp_postgresql" in cmd and "Env" in cmd:
            return "POSTGRES_USER=myapp\nPOSTGRES_PASSWORD=s3cret\nPOSTGRES_DB=myapp\n"
        if "dallinger-postgresql-1" in cmd:
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


def _fake_bin(tmp_path):
    """Fake ``docker``, which logs its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("docker", 'echo "$@" >> "$HOME/docker.log"'),):
        (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    return bin_dir


def test_write_experiment_compose_env_appends_ids_and_creates_home_dirs(tmp_path):
    app_dir = tmp_path / "dallinger" / "demo"
    app_dir.mkdir(parents=True)
    (app_dir / ".env").write_text("POSTGRES_PASSWORD=pw\n")
    docker_ssh_module._write_experiment_compose_env(
        LocalExecutor(tmp_path, _fake_bin(tmp_path)),
        "demo",
        "${HOME}/psynet-data/assets:/psynet-data/assets,/etc/ssl:/certs:ro",
    )
    env = (app_dir / ".env").read_text()
    assert env.startswith("POSTGRES_PASSWORD=pw\n")
    assert f"UID={os.getuid()}\nGID={os.getgid()}\n" in env
    for sub in ("dallinger-data/demo", "psynet-data/assets"):
        assert (tmp_path / sub).is_dir()
    assert not (tmp_path / "docker.log").exists()


def test_remote_bind_mount_dirs_only_chowns_writable_home_subdirs():
    dirs = docker_ssh_module._remote_bind_mount_dirs(
        "./dallinger.log:/experiment/dallinger.log,"
        "${HOME}/psynet-data/assets:/psynet-data/assets,"
        "/etc/ssl:/certs:ro,/srv/data:/data,~:/home,~/configs:/configs:ro",
        "consonance",
    )
    assert dirs == ['"$HOME/dallinger-data/$app"', '"$HOME/psynet-data/assets"']


@pytest.mark.parametrize("label, expected", [("1\n", True), ("\n", False)])
def test_only_labelled_images_run_as_the_ssh_user(label, expected, capsys):
    executor = FakeExecutor({"image inspect": label})
    assert docker_ssh_module._image_runs_as_ssh_user(executor, "img:tag") is expected
    assert ("run as root" in capsys.readouterr().out) is not expected
