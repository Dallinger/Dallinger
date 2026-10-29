import contextlib
import importlib
import os
import shlex
import socket
import subprocess
import sys
import uuid
import zipfile
from unittest import mock

import click
import pytest
from click.testing import CliRunner

from dallinger.command_line.lib.cloudflare import CloudflareError, TunnelDeletion
from dallinger.config import Configuration
from dallinger.docker.tools import docker_tag_from_experiment_id

docker_ssh_module = importlib.import_module("dallinger.command_line.docker_ssh")


@pytest.mark.parametrize(
    "ssh_g_user, advised",
    [("pmch2@cam.ac.uk", False), ("peter", True), (None, True), ("", True)],
)
def test_docker_host_uri_omits_at_sign_usernames(
    monkeypatch, capsys, ssh_g_user, advised
):
    def fake_run(cmd, **kwargs):
        # OpenSSH's `ssh -G` reports the user it would log in as.
        assert cmd[:2] == ["ssh", "-G"] and cmd[-1] == "rr-pc01.example"
        assert kwargs["stdin"] is subprocess.DEVNULL
        if ssh_g_user is None:
            raise FileNotFoundError("ssh")
        if not ssh_g_user:
            return subprocess.CompletedProcess(cmd, 255, "")
        return subprocess.CompletedProcess(cmd, 0, f"port 22\nuser {ssh_g_user}\n")

    monkeypatch.setattr(docker_ssh_module.subprocess, "run", fake_run)
    assert (
        docker_ssh_module.docker_host_uri("rr-pc01.example", user="pmch2@cam.ac.uk")
        == "ssh://rr-pc01.example"
    )
    assert ("User pmch2@cam.ac.uk" in capsys.readouterr().out) == advised
    assert (
        docker_ssh_module.docker_host_uri("musix.example", user="pmch2", port=2222)
        == "ssh://pmch2@musix.example:2222"
    )


class FakeExecutor:
    """Answer remote commands by the first matching substring, in ``replies`` order."""

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
        status, stdout, stderr = self.run_with_status(cmd)
        if raise_ and status:
            raise docker_ssh_module.ExecuteException(stderr)
        return stdout

    def run_with_status(self, cmd):
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            env={"HOME": str(self.home), "PATH": self.path},
        )
        return result.returncode, result.stdout, result.stderr


def _mock_executor(manifest_lines=""):
    return FakeExecutor(
        {
            "for app in ": manifest_lines,
            "caddy.d": "alpha\n/home/test/dallinger/beta/docker-compose.yml\n",
            "docker ps": "beta\n",
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


def test_root_domain_conflicts_ignore_cloudflare_apps():
    cloudflare = docker_ssh_module.DeploymentManifest(
        app="cf", server="lab", public_origin="https://cf.x.org", ingress="cloudflare"
    )

    class Executor:
        def run(self, cmd, raise_=True):
            if cmd.startswith("ls"):
                return "classic\n/h/dallinger/cf/docker-compose.yml\n"
            return "cf\t" + cloudflare.to_json().replace("\n", "") + "\n"

    assert docker_ssh_module._host_caddy_apps(Executor()) == ["classic"]


@pytest.mark.parametrize(
    "command, app, owner",
    [
        ("deploy", "Logs", "the server's log viewer"),
        ("sandbox", "Logs", "the server's log viewer"),
        ("deploy", "caddy.d", "the server's Caddy configuration"),
        ("deploy", "root.d", "the server's Caddy configuration"),
        ("deploy", "dallinger", "the server's shared services"),
        ("deploy", "Dal.linger", "the server's shared services"),
    ],
)
def test_reserved_app_name_is_rejected_up_front(monkeypatch, command, app, owner):
    from click.testing import CliRunner

    hosts = {"lab": {"host": "lab.example"}}
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", hosts)
    monkeypatch.setattr(docker_ssh_module, "get_configured_hosts", lambda: hosts)
    get_experiment_files = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", get_experiment_files)

    result = CliRunner().invoke(
        getattr(docker_ssh_module, command), ["--app", app, "--server", "lab"]
    )

    assert result.exit_code == 2
    assert f'"{app}" is reserved for {owner}; choose another app name.' in result.output
    get_experiment_files.assert_not_called()


def test_deploy_in_mode_rejects_reserved_app_name(monkeypatch):
    get_experiment_files = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", get_experiment_files)

    with pytest.raises(click.UsageError, match="reserved for the server's log viewer"):
        docker_ssh_module._deploy_in_mode(**_deploy_kwargs(app_name="logs"))

    get_experiment_files.assert_not_called()


def test_deploy_rejects_a_reserved_app_name_from_the_archive(monkeypatch, tmp_path):
    archive = tmp_path / "exp.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("experiment_id.md", "logs")
    hosts = {"test-server": {"host": "lab.example"}}
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", hosts)
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: [])
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: mock.MagicMock())
    monkeypatch.setattr(docker_ssh_module, "run_pre_launch_checks", mock.Mock())

    with pytest.raises(click.UsageError, match="reserved for the server's log viewer"):
        docker_ssh_module._deploy_in_mode(
            **_deploy_kwargs(archive_path=str(archive), allow_private_ip=True)
        )


def test_cloudflare_error_prints_one_error_line(monkeypatch):
    from click.testing import CliRunner

    hosts = {"lab": {"host": "lab.example", "default_ingress": "cloudflare"}}
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", hosts)
    monkeypatch.setattr(docker_ssh_module, "get_configured_hosts", lambda: hosts)
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: [])
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: mock.MagicMock())
    monkeypatch.setattr(docker_ssh_module, "run_pre_launch_checks", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module,
        "load_api_token",
        mock.Mock(side_effect=CloudflareError("no token")),
    )

    result = CliRunner().invoke(docker_ssh_module.deploy, ["--server", "lab"])

    assert result.exit_code == 1
    assert result.output.endswith("Error: Cloudflare error: no token\n")
    assert "Aborted!" not in result.output


@pytest.mark.parametrize(
    "default_ingress, expected", [("cloudflare", "from-file"), ("classic", None)]
)
def test_check_deploy_credentials_reads_file_override(
    monkeypatch, tmp_path, default_ingress, expected
):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"lab.example.org": {"host": "lab", "default_ingress": default_ingress}},
    )
    token_file = tmp_path / "token"
    token_file.write_text("from-file\n")
    config = Configuration()
    config.register("cloudflare_api_token", str, ["CLOUDFLARE_API_TOKEN"])
    config.register("other", str)
    config.extend({"cloudflare_api_token": "from-config"})
    config.ready = True
    config.register("cloudflare_keychain_service", str)
    seen_services = []

    def load_api_token(config):
        seen_services.append(config.get("cloudflare_keychain_service", None))
        return config.get("cloudflare_api_token")

    monkeypatch.setattr(docker_ssh_module, "load_api_token", load_api_token)
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: config)
    token = docker_ssh_module.check_deploy_credentials(
        "lab",
        None,
        (
            ("CLOUDFLARE_API_TOKEN", f"file:{token_file}"),
            ("cloudflare_keychain_service", "org.example.token"),
            ("other", f"file:{tmp_path / 'missing'}"),
        ),
    )
    assert token == expected
    assert seen_services == (["org.example.token"] if expected else [])
    assert config.get("cloudflare_api_token") == "from-config"
    assert config.get("cloudflare_keychain_service", None) is None


def test_check_deploy_credentials_reports_a_missing_token_file(monkeypatch, tmp_path):
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"lab": {"host": "lab", "default_ingress": "cloudflare"}},
    )
    config = Configuration()
    config.register("cloudflare_api_token", str)
    config.ready = True
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: config)
    missing = tmp_path / "missing"
    with pytest.raises(click.ClickException, match=f"Could not read {missing}: "):
        docker_ssh_module.check_deploy_credentials(
            "lab", None, (("cloudflare_api_token", f"file:{missing}"),)
        )


def test_check_deploy_credentials_resolves_the_server_like_the_deploy(monkeypatch):
    hosts = {
        "lab.example.org": {"host": "lab", "default_ingress": "cloudflare"},
        "other.example.org": {"host": "other"},
    }
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", hosts)
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: Configuration())
    monkeypatch.setattr(docker_ssh_module, "load_api_token", lambda config: "token")
    check = docker_ssh_module.check_deploy_credentials

    assert check("lab") == "token"
    assert check("lab", ingress="classic") is None
    assert check("other") is None
    assert check("other", ingress="cloudflare") == "token"
    # The deploy hasn't chosen one of several servers yet.
    assert check() is None
    assert check(ingress="cloudflare") == "token"
    with pytest.raises(click.UsageError, match="Unknown server 'missing'"):
        check("missing")
    with pytest.raises(click.UsageError, match="Unknown ingress mode 'tunnel'"):
        check("lab", ingress="tunnel")
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"lab": hosts["lab.example.org"]}
    )
    assert check() == "token"
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {})
    with pytest.raises(click.UsageError, match="No server configured"):
        check()


def test_classic_deploy_without_contact_email_prints_an_error_line(monkeypatch):
    config = Configuration()
    config._reset(register_defaults=True)
    # The value from global_config_defaults.txt.
    config.extend({"contact_email_on_error": "???"})
    config.ready = True
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load=False: config)
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"lab": {"host": "lab.example"}}
    )
    monkeypatch.setattr(docker_ssh_module, "run_pre_launch_checks", mock.Mock())
    with pytest.raises(click.ClickException, match="No Let's Encrypt contact email"):
        docker_ssh_module._deploy_in_mode(
            **_deploy_kwargs(app_name="myapp", server="lab")
        )


def test_cloudflare_deploy_deletes_a_new_tunnel_it_could_not_record(
    monkeypatch, capsys
):
    class Executor:
        def __init__(self, *args, **kwargs):
            pass

        def run(self, cmd, raise_=True):
            return ""

    deleted = []
    monkeypatch.setattr(docker_ssh_module, "Executor", Executor)
    monkeypatch.setattr(docker_ssh_module, "remove_named_volume", lambda *args: None)
    monkeypatch.setattr(docker_ssh_module, "get_sftp", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        docker_ssh_module,
        "ensure_experiment_tunnel",
        lambda **kwargs: {"tunnel_id": "new", "connector_token": "secret"},
    )
    monkeypatch.setattr(
        docker_ssh_module,
        "_install_tunnel_token",
        mock.Mock(side_effect=OSError("sftp failed")),
    )
    monkeypatch.setattr(
        docker_ssh_module,
        "delete_experiment_tunnel",
        lambda **kwargs: deleted.append(kwargs["own_tunnel_id"]),
    )
    with pytest.raises(OSError):
        docker_ssh_module._deploy_cloudflare_in_mode(
            api_token="token",
            archive_path=None,
            config={},
            config_options={},
            dashboard_password="pw",
            dashboard_user="admin",
            experiment_id="myapp",
            experiment_uuid="uuid",
            image_name="image",
            mode="sandbox",
            push_build=False,
            server="lab",
            server_info={"host": "lab.example"},
            settings={"account_id": "acct", "zone_id": "zone", "dns_zone": "x.org"},
            update=False,
        )
    assert deleted == ["new"]
    assert capsys.readouterr().out.startswith("Setting up the Cloudflare tunnel...\n")


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
            (" down", "down"),
            ("down -v", "down -v"),
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


def test_destroy_cloudflare_stops_connector_before_deleting_the_tunnel(
    monkeypatch, capsys
):
    removed = TunnelDeletion(True, "dallinger-myapp", "myapp.science-of-music.org")
    order = _cloudflare_destroy(monkeypatch, removed=removed)
    docker_ssh_module.destroy.callback(
        server="test-server", app="myapp", keep_data=True
    )
    assert order == ["stop", ("delete", "myapp", "acct"), ("own", "tun"), "down", "rm"]
    assert (
        "Deleted Cloudflare tunnel dallinger-myapp and DNS record "
        "myapp.science-of-music.org." in capsys.readouterr().out
    )


def test_destroy_uses_the_cloudflare_ids_recorded_at_deploy(monkeypatch):
    recorded = {
        "account_id": "deploy-acct",
        "zone_id": "deploy-zone",
        "dns_zone": "x.org",
    }
    order = _cloudflare_destroy(
        monkeypatch, removed=TunnelDeletion(True), cloudflare=recorded
    )
    docker_ssh_module.destroy.callback(
        server="test-server", app="myapp", keep_data=True
    )
    assert ("delete", "myapp", "deploy-acct") in order


def test_destroy_keeps_the_app_when_cloudflare_cleanup_fails(monkeypatch, capsys):
    removed = TunnelDeletion(False, hostname="myapp.x.org")
    order = _cloudflare_destroy(monkeypatch, removed=removed)
    with pytest.raises(click.Abort):
        docker_ssh_module.destroy.callback(
            server="test-server", app="myapp", keep_data=True
        )
    assert order == ["stop", ("delete", "myapp", "acct"), ("own", "tun")]
    out = capsys.readouterr().out
    assert "Deleted DNS record myapp.x.org." in out
    assert "Cloudflare cleanup failed." in out


@pytest.mark.parametrize(
    "removed, message",
    [
        (TunnelDeletion(True), "No Cloudflare tunnel or DNS record left to delete"),
        (
            TunnelDeletion(True, skipped_tunnel_name="dallinger-myapp"),
            "Left Cloudflare tunnel dallinger-myapp in place",
        ),
    ],
)
def test_destroy_reports_cloudflare_resources_left(
    monkeypatch, capsys, removed, message
):
    _cloudflare_destroy(monkeypatch, removed=removed)
    docker_ssh_module.destroy.callback(
        server="test-server", app="myapp", keep_data=True
    )
    assert message in capsys.readouterr().out


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


@pytest.mark.parametrize(
    "name, expected",
    [
        ("pc01.lab.example.org", "pc01.lab.example.org"),
        ("pc01", "pc01.lab.example.org"),
        ("10.0.0.5", "10.0.0.5"),
        ("[::1]:2200", "[::1]:2200"),
        ("pc04", "pc04:2200"),
    ],
)
def test_resolve_server_name(name, expected):
    hosts = [
        "pc01.lab.example.org",
        "pc02.a.org",
        "pc02.b.org",
        "10.0.0.5",
        "[::1]:2200",
        "pc04:2200",
        "pc05:abc",
    ]
    assert docker_ssh_module.resolve_server_name(name, hosts) == expected


@pytest.mark.parametrize(
    "name, error",
    [
        ("pc02", "ambiguous. It matches: pc02.a.org, pc02.b.org"),
        ("pc03", "Unknown server 'pc03'. Configured servers:"),
        ("10", "Unknown server '10'"),
    ],
)
@pytest.mark.parametrize("ip_host", ["10.0.0.5", "10.0.0.5:2222"])
def test_resolve_server_name_errors(name, error, ip_host):
    hosts = ["pc01.lab.example.org", "pc02.a.org", "pc02.b.org", ip_host]
    with pytest.raises(ValueError, match=error):
        docker_ssh_module.resolve_server_name(name, hosts)


def test_server_option_accepts_short_name(monkeypatch):
    from click.testing import CliRunner

    hosts = {"pc01.lab.example.org": {"host": "pc01.lab.example.org"}, "other": {}}
    monkeypatch.setattr(docker_ssh_module, "get_configured_hosts", lambda: hosts)
    get_apps = mock.Mock(return_value=[])
    monkeypatch.setattr(docker_ssh_module, "get_apps", get_apps)

    result = CliRunner().invoke(docker_ssh_module.apps, ["--server", "pc01"])

    assert result.exit_code == 0, result.output
    get_apps.assert_called_once_with("pc01.lab.example.org")


def test_root_domain_auto_destroy_uses_full_server_name(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"pc01.lab.example.org": {"host": "pc01.lab.example.org"}},
    )
    monkeypatch.setattr(docker_ssh_module, "_executor_for_server", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module, "_host_caddy_apps", mock.Mock(side_effect=[["old"], []])
    )
    monkeypatch.setattr(sys, "stdin", mock.Mock(isatty=lambda: True))
    monkeypatch.setattr(docker_ssh_module.click, "confirm", lambda *a, **k: True)
    destroy = mock.Mock()
    monkeypatch.setattr(docker_ssh_module.destroy, "callback", destroy)

    assert docker_ssh_module.ensure_root_domain_ready("pc01", update=False)
    destroy.assert_called_once_with(
        server="pc01.lab.example.org",
        app="old",
        keep_data=True,
        delete_data_command=None,
    )

    docker_ssh_module._host_caddy_apps.side_effect = [["old"], ["old"]]
    with pytest.raises(click.ClickException, match="still present: old"):
        docker_ssh_module.ensure_root_domain_ready("pc01", update=False)


def test_root_domain_deploy_without_a_terminal_lists_destroy_commands(monkeypatch):
    from click.testing import CliRunner

    hosts = {
        "pc01.lab.example.org": {
            "host": "pc01.lab.example.org",
            "contact_email": "lab@example.org",
        }
    }
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", hosts)
    monkeypatch.setattr(docker_ssh_module, "get_configured_hosts", lambda: hosts)
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: [])
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: mock.MagicMock())
    monkeypatch.setattr(docker_ssh_module, "run_pre_launch_checks", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module,
        "_classic_preflight",
        lambda *args, **kwargs: "pc01.lab.example.org",
    )
    monkeypatch.setattr(docker_ssh_module, "_executor_for_server", mock.Mock())
    monkeypatch.setattr(docker_ssh_module, "Executor", mock.MagicMock())
    image_client = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "_image_docker_client", image_client)
    monkeypatch.setattr(
        docker_ssh_module, "_host_caddy_apps", lambda executor: ["old", "older"]
    )
    destroy = mock.Mock()
    monkeypatch.setattr(docker_ssh_module.destroy, "callback", destroy)

    result = CliRunner().invoke(
        docker_ssh_module.deploy, ["--server", "pc01", "--allow-private-ip"]
    )

    assert result.exit_code == 1
    assert result.output.startswith(
        "Error: Deploying to the root domain of pc01.lab.example.org requires "
        "destroying its classic-ingress experiments first: old, older."
    )
    for app in ("old", "older"):
        assert (
            f"  dallinger docker-ssh destroy --app {app} --server "
            "pc01.lab.example.org --keep-data\n" in result.output + "\n"
        )
    assert "Aborted!" not in result.output
    destroy.assert_not_called()
    # The configured image is neither looked up nor pushed.
    image_client.assert_not_called()


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


def _deploy_kwargs(**overrides):
    return {
        "app_name": None,
        "archive_path": None,
        "config_options": (),
        "dns_host": None,
        "mode": "live",
        "server": "test-server",
        "update": False,
        "local_build": False,
        "push_build": False,
        **overrides,
    }


def test_invalid_policy_stops_before_docker_ssh_external_side_effects(
    tmp_path, monkeypatch
):
    (tmp_path / "deploy.toml").write_text("version = 999\nexclude = []\n")
    monkeypatch.chdir(tmp_path)
    get_config = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "get_config", get_config)

    with pytest.raises(click.UsageError, match="version"):
        docker_ssh_module._deploy_in_mode(**_deploy_kwargs())

    get_config.assert_not_called()


def test_deploy_runs_its_checks_before_building_the_image(monkeypatch):
    """A bad --dns-host or recruiter setting must not cost an image build."""
    events = []
    source = object()
    config = Configuration()
    config._reset(register_defaults=True)
    config.ready = True

    def step(name, result=None):
        def run(*args, **kwargs):
            events.append(name)
            return result

        return run

    def build(config, experiment_files, *args, **kwargs):
        events.append("build")
        assert experiment_files is source
        assert config.get("docker_image_name") == "registry.example/exp:1"
        raise click.Abort()

    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"lab": {"host": "lab.example.org"}}
    )
    monkeypatch.setattr(docker_ssh_module, "_ipv4_addresses", lambda host: [])
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: config)
    for name, event, result in (
        ("get_experiment_files", "policy", source),
        ("run_pre_launch_checks", "recruiter", None),
        ("_server_tls", "tls", "tls internal"),
        ("_classic_preflight", "dns-and-server-check", "lab.example.org"),
    ):
        monkeypatch.setattr(docker_ssh_module, name, step(event, result))
    monkeypatch.setattr(
        docker_ssh_module, "_check_compose_project_free", step("compose-project")
    )
    root_domain = mock.Mock(wraps=docker_ssh_module.ensure_root_domain_ready)
    app_slot = mock.Mock(side_effect=step("app-slot"))
    monkeypatch.setattr(docker_ssh_module, "ensure_root_domain_ready", root_domain)
    monkeypatch.setattr(docker_ssh_module, "_executor_for_server", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module, "_host_caddy_apps", mock.Mock(side_effect=[["old"], []])
    )
    monkeypatch.setattr(docker_ssh_module, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(docker_ssh_module.click, "confirm", step("confirm", True))
    monkeypatch.setattr(docker_ssh_module.destroy, "callback", step("destroy"))
    monkeypatch.setattr(docker_ssh_module, "_check_app_slot", app_slot)
    executor = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "Executor", executor)
    monkeypatch.setattr(docker_ssh_module, "_built_image", build)
    monkeypatch.setattr(
        docker_ssh_module,
        "_image_usable_from_registry",
        step("registry-image", True),
    )
    monkeypatch.setattr(
        docker_ssh_module,
        "_image_docker_client",
        lambda *args: contextlib.nullcontext(),
    )

    with pytest.raises(click.Abort):
        docker_ssh_module._deploy_in_mode(
            **_deploy_kwargs(
                server="lab",
                config_options=(("docker_image_name", "registry.example/exp:1"),),
                delete_data_command="wrapper rm {app}",
            )
        )

    # Executors share one SSH connection, which the build reuses.
    executor.return_value.client.close.assert_not_called()

    assert events == [
        "policy",
        "recruiter",
        "tls",
        "dns-and-server-check",
        "compose-project",
        "confirm",
        "registry-image",
        "destroy",
        "app-slot",
        "build",
    ]
    assert root_domain.call_args.kwargs["new_app"] == app_slot.call_args.args[1]
    assert root_domain.call_args.kwargs["delete_data_command"] == "wrapper rm {app}"
    for command in docker_ssh_module.deploy, docker_ssh_module.sandbox:
        assert "delete_data_command" in {param.name for param in command.params}


@pytest.mark.parametrize(
    "build_option, image_name, registry",
    [
        ("push_build", None, None),
        ("local_build", None, None),
        (None, None, None),
        ("local_build", "registry.example/exp:1", "found"),
        ("local_build", "registry.example/exp:1", "down"),
        (None, "registry.example/exp:1", "missing"),
    ],
)
def test_image_base_name_and_configured_image_are_checked_before_cleanup(
    monkeypatch, capsys, build_option, image_name, registry
):
    """Deploys that can't get an image stop before the root-domain cleanup.

    Without ``docker_image_name``, a pushed build with no base name stops
    before the pre-launch checks, and a server-only build reaches the
    cleanup and the build. With ``docker_image_name``, the registry is
    consulted before the cleanup destroys anything: an image it has is
    reused without a base name; if it can't be checked, a pushed rebuild
    stops for the missing base name; and an image that can't be found at
    all aborts.
    """
    import docker

    config = Configuration()
    config._reset(register_defaults=True)
    config.ready = True
    destroyed = mock.Mock()

    def root_domain(before_destroy, **kwargs):
        if before_destroy:
            before_destroy()
        destroyed()

    build = mock.Mock(side_effect=click.Abort)
    docker_client = mock.Mock()
    if registry == "down":
        docker_client.images.get_registry_data.side_effect = RuntimeError("down")
    elif registry == "missing":
        docker_client.images.get_registry_data.side_effect = (
            docker.errors.ImageNotFound("missing")
        )
        docker_client.images.push.return_value = '{"error": "not found"}\r\n'
    monkeypatch.setattr(
        docker_ssh_module,
        "_image_docker_client",
        lambda *args: contextlib.nullcontext(docker_client),
    )
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"lab": {"host": "lab.example.org"}}
    )
    monkeypatch.setattr(docker_ssh_module, "_ipv4_addresses", lambda host: [])
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: config)
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: None)
    pre_launch_checks = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "run_pre_launch_checks", pre_launch_checks)
    monkeypatch.setattr(docker_ssh_module, "ensure_root_domain_ready", root_domain)
    monkeypatch.setattr(docker_ssh_module, "_built_image", build)
    monkeypatch.setattr(docker_ssh_module, "_server_tls", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module,
        "_classic_preflight",
        mock.Mock(return_value="lab.example.org"),
    )
    for name in ("_check_compose_project_free", "_check_app_slot"):
        monkeypatch.setattr(docker_ssh_module, name, mock.Mock())
    monkeypatch.setattr(docker_ssh_module, "Executor", mock.Mock())
    kwargs = _deploy_kwargs(
        server="lab",
        config_options=(("docker_image_name", image_name),) if image_name else (),
        **({build_option: True} if build_option else {}),
    )

    if registry == "missing":
        with pytest.raises(click.Abort):
            docker_ssh_module._deploy_in_mode(**kwargs)
        assert "Could not find image" in capsys.readouterr().out
        destroyed.assert_not_called()
        return
    if build_option is None or registry == "found":
        with pytest.raises(click.Abort):
            docker_ssh_module._deploy_in_mode(**kwargs)
        pre_launch_checks.assert_called_once()
        destroyed.assert_called_once()
        assert build.call_args.kwargs["image_usable"] == (
            True if registry == "found" else None
        )
        return
    with pytest.raises(click.ClickException, match="docker_image_base_name"):
        docker_ssh_module._deploy_in_mode(**kwargs)
    assert pre_launch_checks.called == bool(image_name)
    destroyed.assert_not_called()
    build.assert_not_called()


def test_cloudflare_deploy_without_api_token_stops_before_the_build(monkeypatch):
    config = Configuration()
    config._reset(register_defaults=True)
    config.ready = True
    config.extend(
        {
            "cloudflare_account_id": "acct",
            "cloudflare_zone_id": "zone",
            "cloudflare_dns_zone": "x.org",
        }
    )
    build = mock.Mock()
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"lab": {"host": "lab.example", "default_ingress": "cloudflare"}},
    )
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: config)
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: None)
    monkeypatch.setattr(docker_ssh_module, "run_pre_launch_checks", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module,
        "load_api_token",
        mock.Mock(side_effect=docker_ssh_module.CloudflareError("no token")),
    )
    monkeypatch.setattr(docker_ssh_module, "_built_image", build)

    with pytest.raises(click.ClickException, match="no token"):
        docker_ssh_module._deploy_in_mode(**_deploy_kwargs(server="lab"))

    build.assert_not_called()


def test_deploy_reports_a_missing_config_option_file(monkeypatch, tmp_path):
    config = Configuration()
    config._reset(register_defaults=True)
    config.ready = True
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"lab": {"host": "lab.example"}}
    )
    monkeypatch.setattr(docker_ssh_module, "_ipv4_addresses", lambda host: [])
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: config)
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: None)
    missing = tmp_path / "missing"

    with pytest.raises(click.ClickException, match=f"Could not read {missing}: "):
        docker_ssh_module._deploy_in_mode(
            **_deploy_kwargs(
                server="lab",
                config_options=(("cloudflare_api_token", f"file:{missing}"),),
            )
        )


@pytest.mark.parametrize(
    "configured, app, base_name",
    [
        ("base-image", "My_Study", "base-image"),
        (None, "My_Study", "my_study"),
        (None, None, "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
    ],
)
def test_docker_ssh_build_assembles_the_validated_source(
    tmp_path, monkeypatch, configured, app, base_name
):
    pytest.importorskip("docker")
    source = mock.Mock(deployment_plan=object())
    config = mock.Mock()
    config.get.side_effect = lambda key, default=None: {
        "docker_image_name": None,
        "docker_image_base_name": configured,
        "id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    }.get(key, default)
    config.as_dict.return_value = {"example": "value"}
    setup = mock.Mock(return_value=("experiment-id", tmp_path / "assembly"))

    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"test-server": {"host": "host"}}
    )
    with (
        mock.patch.object(docker_ssh_module, "setup_experiment", setup),
        mock.patch.object(docker_ssh_module, "ensure_remote_host_in_known_hosts"),
        mock.patch.object(docker_ssh_module, "add_server_pem_to_ssh_agent"),
        mock.patch("docker.from_env", return_value=mock.Mock()),
        mock.patch(
            "dallinger.docker.tools.build_image", return_value="built:image"
        ) as build_image,
    ):
        image_name = docker_ssh_module._build_and_push_image(
            config,
            source,
            None,
            "test-server",
            local_build=False,
            push_build=False,
            app=app,
        )

    assert image_name == "built:image"
    assert setup.call_args.kwargs["experiment_files"] is source
    assert build_image.call_args.args[1] == base_name
    assert build_image.call_args.kwargs["image_tag"] == (
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    )
    assert setup.call_args.kwargs["quiet"] is True
    assert build_image.call_args.kwargs["quiet"] is True


def test_docker_ssh_local_build_pushes_without_reassembling(tmp_path):
    source = mock.Mock(deployment_plan=object())
    config = mock.Mock()
    config.get.side_effect = lambda key, default=None: {
        "docker_image_name": None,
        "docker_image_base_name": "base-image",
        "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    }.get(key, default)
    config.as_dict.return_value = {}
    setup = mock.Mock(return_value=("experiment-id", tmp_path / "assembly"))
    docker_cli = importlib.import_module("dallinger.command_line.docker")
    fake_docker = mock.MagicMock()
    fake_tools = mock.Mock()
    fake_tools.build_image.return_value = "built:image"
    fake_tools.docker_tag_from_experiment_id = docker_tag_from_experiment_id

    with (
        mock.patch.object(docker_ssh_module, "setup_experiment", setup),
        mock.patch.dict(
            sys.modules,
            {"docker": fake_docker, "dallinger.docker.tools": fake_tools},
        ),
        mock.patch.object(
            docker_cli, "push_image", return_value="pushed:image"
        ) as push_image,
    ):
        image_name = docker_ssh_module._build_and_push_image(
            config, source, None, "test-server", local_build=True, push_build=False
        )

    assert image_name == "pushed:image"
    setup.assert_called_once()
    push_image.assert_called_once_with("built:image")
    assert fake_tools.build_image.call_args.kwargs["image_tag"] == (
        "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    )


def test_experiment_image_from_compose_reads_web_not_infra_images():
    yml = docker_ssh_module.get_docker_compose_yml(
        {
            "worker_processes": 2,
            "clock_on": True,
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


def test_remove_experiment_image_runs_docker_rmi_without_force(capsys):
    executor = mock.Mock()
    executor.run.return_value = "kept\n"
    docker_ssh_module.remove_experiment_image(executor, "registry/exp:old-uid")
    command = executor.run.call_args[0][0]
    assert "docker rmi registry/exp:old-uid" in command
    assert "--force" not in command
    assert "Kept experiment image registry/exp:old-uid (still in use).\n" in (
        capsys.readouterr().out
    )


def test_remove_unshared_skips_rmi_when_another_app_pins_the_image():
    executor = mock.Mock()
    executor.run.return_value = "/home/ubuntu/dallinger/otherapp/docker-compose.yml\n"
    docker_ssh_module.remove_unshared_experiment_image(
        executor, "registry/exp:shared", except_app="myapp"
    )
    commands = [call.args[0] for call in executor.run.call_args_list]
    assert any(cmd.startswith("grep -xF -l") for cmd in commands)
    assert not any("docker rmi" in cmd for cmd in commands)


def _patch_destroy_executor(monkeypatch, run):
    executor = mock.Mock()
    executor.run.side_effect = run
    executor.run_with_status.side_effect = lambda cmd: (0, run(cmd), "")
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"test-server": {"host": "example.com", "user": "ubuntu"}},
    )
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *args, **kwargs: executor)
    return executor


def test_destroy_removes_unique_image_after_down_not_infra(monkeypatch, capsys):
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
        if "docker rmi" in cmd:
            return "removed\n"
        return ""

    _patch_destroy_executor(monkeypatch, run)
    docker_ssh_module.destroy.callback(
        server="test-server", app="myapp", keep_data=True
    )

    down = "docker compose -f ~/dallinger/myapp/docker-compose.yml down"
    rm_tree = "rm -rf ~/dallinger/myapp/"
    rmi_commands = [cmd for cmd in commands if "docker rmi" in cmd]
    assert len(rmi_commands) == 1
    assert "docker rmi registry/exp:old-uid" in rmi_commands[0]
    rmi = rmi_commands[0]
    assert commands.index(down) < commands.index(rmi) < commands.index(rm_tree)
    out = capsys.readouterr().out
    assert "Removed experiment image registry/exp:old-uid.\n" in out
    assert out.endswith("App myapp removed.\n")
    for forbidden in (
        "redis",
        "postgres:12",
        "caddy:2",
        "pgbouncer",
        "amir20/dozzle",
    ):
        assert not any(forbidden in cmd for cmd in rmi_commands)


def _destroy_with_data(monkeypatch, args=(), input=None, **server):
    commands = _server_with_data(monkeypatch, **server)
    result = CliRunner().invoke(
        docker_ssh_module.destroy,
        ["--app", "myapp", "--server", "test-server", *args],
        input=input,
    )
    return commands, result


def _server_with_data(
    monkeypatch,
    tty=True,
    deployed=True,
    db="12 MB",
    volumes=("myapp_redis_data",),
    folder=True,
    down_status=0,
    own_db="",
    tunnel_token=False,
    server_apps="myapp\n",
):
    commands = []

    def run(cmd, raise_=True):
        commands.append(cmd)
        if cmd.startswith("ls -1 ~/dallinger/caddy.d"):
            return server_apps
        if cmd.startswith("test -f") and "cloudflare-tunnel-token" in cmd:
            return "Yes" if tunnel_token else ""
        if cmd.startswith("test -f") and "docker-compose.yml" in cmd:
            return "Yes" if deployed else ""
        if cmd.startswith("if [ -L ~/dallinger-data/myapp ]"):
            return "dir\n" if folder else ""
        if cmd.startswith("timeout 15 du"):
            return "3.4G\t/home/u/dallinger-data/myapp\nrc=0\n"
        return ""

    def run_with_status(cmd):
        commands.append(cmd)
        if "pg_database_size(datname)" in cmd:
            if db is None:
                return 1, "", "service postgresql is not running\n"
            if db == "timeout":
                return 124, "", ""
            return 0, f"{db}|t\n" if db else "|f\n", ""
        if "docker exec myapp_postgresql" in cmd:
            return 0, own_db, ""
        if cmd.startswith("docker volume ls"):
            if volumes is None:
                return 1, "", "Cannot connect to the Docker daemon\n"
            return 0, "\n".join(volumes), ""
        if "removed $kind" in cmd:
            return 0, "removed dir\n", ""
        if cmd.endswith("docker-compose.yml down"):
            return down_status, "", "network in use\n"
        return 0, "", ""

    executor = _patch_destroy_executor(monkeypatch, run)
    executor.run_with_status.side_effect = run_with_status
    monkeypatch.setattr(
        docker_ssh_module,
        "get_configured_hosts",
        lambda: docker_ssh_module.CONFIGURED_HOSTS,
    )
    monkeypatch.setattr(docker_ssh_module, "_stdin_is_tty", lambda: tty)
    return commands


def _deletes(commands):
    return [
        c
        for c in commands
        if "DROP" in c or "docker volume rm" in c or "removed $kind" in c
    ]


def test_destroy_remove_data_deletes_classic_database_redis_and_folder(monkeypatch):
    commands, result = _destroy_with_data(monkeypatch, ["--remove-data", "--yes"])
    assert result.exit_code == 0, result.output
    drop_db, drop_user, volume, folder = _deletes(commands)
    down = "docker compose -f ~/dallinger/myapp/docker-compose.yml down"
    assert commands.index(down) < commands.index(drop_db)
    args = shlex.split(drop_db)
    terminate, drop = [args[i + 1] for i, arg in enumerate(args) if arg == "-c"]
    assert "pg_terminate_backend" in terminate and "datname = 'myapp'" in terminate
    assert drop == 'DROP DATABASE IF EXISTS "myapp"'
    assert shlex.split(drop_user)[-1] == 'DROP USER IF EXISTS "myapp"'
    assert volume == "docker volume rm myapp_redis_data"
    ps = "docker ps -q --filter label=com.docker.compose.project=myapp"
    assert commands.index(down) < commands.index(ps) < commands.index(drop_db)
    assert "Deleted the database myapp (12 MB) in the shared Postgres.\n" in (
        result.output
    )


def test_destroy_asks_and_reports_kept_data(monkeypatch):
    commands, result = _destroy_with_data(monkeypatch, input="n\n")
    assert result.exit_code == 0, result.output
    assert not _deletes(commands)
    out = result.output
    assert "  - the database myapp (12 MB) in the shared Postgres" in out
    assert "  - the Postgres user myapp" in out
    assert "  - the Redis volume myapp_redis_data" in out
    assert "  - the folder ~/dallinger-data/myapp (3.4G)" in out
    assert "Delete this data? This cannot be undone. Answer no to keep it." in out
    kept = out.index("Kept the experiment data of myapp on example.com:")
    assert kept > out.index("Delete this data?")
    assert "  - the folder ~/dallinger-data/myapp" in out[kept:]
    assert (
        "dallinger docker-ssh destroy --app myapp --server test-server --remove-data"
        in out
    )

    _, result = _destroy_with_data(
        monkeypatch,
        ["--keep-data"],
        volumes=("myapp_postgres_data",),
        own_db="11 MB\n",
    )
    assert result.exit_code == 0, result.output
    assert "Kept the experiment data of myapp on example.com:" in result.output
    assert (
        "  - the database myapp (11 MB) in the volume myapp_postgres_data"
        in result.output
    )
    assert "  - the folder ~/dallinger-data/myapp (3.4G)" in result.output


def test_destroy_prints_the_callers_delete_data_command(monkeypatch):
    _, result = _destroy_with_data(
        monkeypatch, ["--keep-data", "--delete-data-command", "wrapper rm myapp"]
    )
    assert result.exit_code == 0, result.output
    assert "To delete it, run: wrapper rm myapp" in result.output
    assert "dallinger docker-ssh destroy" not in result.output


@pytest.mark.parametrize(
    "new_app, kept, delete_command, printed",
    [
        (
            "dlgr-new",
            "Their data is kept.",
            None,
            "dallinger docker-ssh destroy --app myapp --server test-server "
            "--remove-data",
        ),
        (
            "myapp",
            "Their data is kept, but this deploy replaces the database and "
            "Redis volume of myapp.",
            "wrapper destroy {app} --remove-data",
            "wrapper destroy myapp --remove-data",
        ),
    ],
)
def test_root_domain_teardown_keeps_data_without_asking(
    monkeypatch, capsys, new_app, kept, delete_command, printed
):
    commands = _server_with_data(monkeypatch, tty=True)
    monkeypatch.setattr(docker_ssh_module, "_executor_for_server", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module, "_host_caddy_apps", mock.Mock(side_effect=[["myapp"], []])
    )
    prompts = []
    monkeypatch.setattr(
        docker_ssh_module.click,
        "confirm",
        lambda text, **kwargs: prompts.append(text) or True,
    )

    assert docker_ssh_module.ensure_root_domain_ready(
        "test-server",
        update=False,
        new_app=new_app,
        delete_data_command=delete_command,
    )
    assert prompts == [
        f"Destroy these experiments automatically before proceeding? {kept}"
    ]
    assert "docker compose -f ~/dallinger/myapp/docker-compose.yml down" in commands
    assert not _deletes(commands)
    out = capsys.readouterr().out
    assert (
        "  dallinger docker-ssh destroy --app myapp --server test-server --keep-data"
        in out
    )
    assert "  - the folder ~/dallinger-data/myapp (3.4G)" in out
    assert f"To delete it, run: {printed}\n" in out


def test_declined_root_domain_teardown_skips_before_destroy(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"lab": {"host": "lab.example"}}
    )
    monkeypatch.setattr(docker_ssh_module, "_executor_for_server", mock.Mock())
    monkeypatch.setattr(docker_ssh_module, "_host_caddy_apps", lambda e: ["old"])
    monkeypatch.setattr(docker_ssh_module, "_stdin_is_tty", lambda: True)
    monkeypatch.setattr(docker_ssh_module.click, "confirm", lambda *a, **k: False)
    before_destroy = mock.Mock()

    with pytest.raises(click.Abort):
        docker_ssh_module.ensure_root_domain_ready(
            "lab", update=False, before_destroy=before_destroy
        )
    before_destroy.assert_not_called()


def test_root_domain_teardown_destroys_nothing_if_an_app_name_is_invalid(
    monkeypatch,
):
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"lab": {"host": "lab.example"}}
    )
    monkeypatch.setattr(docker_ssh_module, "_executor_for_server", mock.Mock())
    monkeypatch.setattr(
        docker_ssh_module, "_host_caddy_apps", lambda executor: ["good", "good~"]
    )
    confirm = mock.Mock()
    destroy = mock.Mock()
    monkeypatch.setattr(docker_ssh_module.click, "confirm", confirm)
    monkeypatch.setattr(docker_ssh_module.destroy, "callback", destroy)

    with pytest.raises(click.ClickException) as error:
        docker_ssh_module.ensure_root_domain_ready("lab", update=False)

    assert not confirm.called and not destroy.called
    message = error.value.message
    assert "Can't destroy 'good~' automatically" in message
    assert "nothing was destroyed" in message
    assert (
        "rm -rf ~/dallinger/'good~' ~/dallinger/caddy.d/'good~' "
        "~/dallinger/root.d/'good~'" in message
    )
    assert "'good'" not in message and " down" not in message


def test_destroy_remove_data_asks_before_teardown(monkeypatch):
    commands, result = _destroy_with_data(monkeypatch, ["--remove-data"], input="n\n")
    assert result.exit_code == 1
    assert not any(" down" in c or "rm -" in c for c in commands)
    assert not _deletes(commands)


def test_destroy_without_a_tty_keeps_data_unless_told_to_delete_it(monkeypatch):
    commands, result = _destroy_with_data(monkeypatch, [], tty=False)
    assert result.exit_code == 0, result.output
    assert "App myapp removed" in result.output and not _deletes(commands)
    assert "Kept the experiment data of myapp on example.com:" in result.output
    assert "To delete it, run:" in result.output

    commands, result = _destroy_with_data(monkeypatch, ["--remove-data"], tty=False)
    assert result.exit_code == 2 and commands == []
    assert "pass --yes in non-interactive sessions" in result.output

    commands, result = _destroy_with_data(
        monkeypatch, ["--remove-data", "--yes"], tty=False
    )
    assert result.exit_code == 0, result.output
    assert "docker volume rm myapp_redis_data" in _deletes(commands)

    commands, result = _destroy_with_data(monkeypatch, [], tty=False, deployed=False)
    assert result.exit_code == 1 and not _deletes(commands)
    assert "Kept the experiment data of myapp on example.com:" in result.output
    assert "App myapp is not deployed, so nothing was destroyed." in result.output

    commands, result = _destroy_with_data(
        monkeypatch, [], tty=False, server_apps="MyApp\nmyapp\n"
    )
    assert result.exit_code == 0, result.output
    assert any(" down" in c for c in commands) and not _deletes(commands)


def test_destroy_remove_data_after_destroy_cleans_up_leftovers(monkeypatch):
    volumes = ("myapp_postgres_data", "myapp_redis_data", "otherapp_redis_data")
    commands, result = _destroy_with_data(
        monkeypatch, ["--remove-data", "--yes"], deployed=False, volumes=volumes
    )
    assert result.exit_code == 0, result.output
    assert "Deleted the database volume myapp_postgres_data" in result.output
    assert not any(" down" in c for c in commands)
    drop_db, drop_user, *volume_rms, folder = _deletes(commands)
    assert volume_rms == [
        "docker volume rm myapp_postgres_data",
        "docker volume rm myapp_redis_data",
    ]

    for args, answer in ([], "n\n"), (["--keep-data"], None):
        commands, result = _destroy_with_data(
            monkeypatch, args, input=answer, deployed=False
        )
        assert result.exit_code == 1 and not _deletes(commands)
        assert "Kept the experiment data of myapp on example.com:" in result.output
        assert "App myapp is not deployed, so nothing was destroyed." in result.output

    nothing_left = dict(deployed=False, db="", volumes=(), folder=False)
    for args in [], ["--keep-data"]:
        _, result = _destroy_with_data(monkeypatch, args, **nothing_left)
        assert result.exit_code == 1
        assert "No experiment data of myapp is left on example.com." in result.output

    for args in ["--remove-data", "--yes"], ["--remove-data"]:
        commands, result = _destroy_with_data(monkeypatch, args, **nothing_left)
        assert result.exit_code == 0, result.output
        assert "Nothing left to delete for myapp on example.com." in result.output
        assert "Aborted" not in result.output and "not deployed" not in result.output
        assert not _deletes(commands)


def test_destroy_stops_if_compose_down_fails(monkeypatch):
    commands, result = _destroy_with_data(
        monkeypatch, ["--remove-data", "--yes"], down_status=1
    )
    assert result.exit_code == 1
    assert "Could not stop the containers of myapp" in result.output
    assert "rm -rf ~/dallinger/myapp/" not in commands and not _deletes(commands)


@pytest.mark.parametrize(
    "unchecked, label",
    [
        ({"volumes": None}, "the Docker volumes of myapp, if any (could not check:"),
        (
            {"db": None},
            "the database myapp in the shared Postgres, if any (could not check: "
            "service postgresql is not running)",
        ),
        (
            {"db": "timeout"},
            "the database myapp in the shared Postgres, if any (could not check: "
            "timed out after 30 s; the server may be busy, so try again)",
        ),
    ],
)
def test_destroy_remove_data_fails_if_some_data_cant_be_checked(
    monkeypatch, unchecked, label
):
    args = ["--remove-data", "--yes", "--delete-data-command", "wrapper rm myapp"]
    _, result = _destroy_with_data(monkeypatch, args, **unchecked)
    assert result.exit_code == 1
    assert f"Did not delete {label}" in result.output
    assert "Some data of myapp was not deleted" in result.output
    assert "and run: wrapper rm myapp" in result.output


@pytest.mark.parametrize(
    "db, dropped, notes",
    [
        (
            "timeout",
            False,
            [
                "Could not check whether the shared Postgres still has a database "
                "myapp from an earlier classic deploy of this name (timed out "
                "after 30 s; the server may be busy).",
                "--remove-data again when the server is less busy.",
            ],
        ),
        (
            None,
            False,
            [
                "(service postgresql is not running).",
                "--remove-data again after fixing the problem.",
            ],
        ),
        (
            "12 MB",
            True,
            ["Deleted the database myapp (12 MB) in the shared Postgres"],
        ),
    ],
)
def test_destroy_cloudflare_only_reports_a_shared_database_it_finds(
    monkeypatch, db, dropped, notes
):
    monkeypatch.setattr(
        docker_ssh_module, "_destroy_cloudflare_resources", lambda *a, **k: True
    )
    commands, result = _destroy_with_data(
        monkeypatch,
        ["--remove-data", "--yes"],
        db=db,
        deployed=False,
        tunnel_token=True,
    )
    assert result.exit_code == 0, result.output
    assert "Did not delete" not in result.output
    assert all(note in result.output for note in notes)
    assert any("DROP DATABASE" in c for c in commands) == dropped


def test_destroy_rejects_both_data_choices(monkeypatch):
    commands, result = _destroy_with_data(monkeypatch, ["--remove-data", "--keep-data"])
    assert result.exit_code == 2 and commands == []
    assert "Pass only one of --remove-data and --keep-data." in result.output


def test_destroy_keeps_data_shared_with_another_app(monkeypatch):
    shared = dict(server_apps="MyApp\nmyapp\n", volumes=("myapp_redis_data",))
    for args in ["--remove-data", "--yes"], []:
        commands, result = _destroy_with_data(monkeypatch, args, **shared)
        assert result.exit_code == 1
        assert "The data of myapp can't be deleted while MyApp exists" in result.output
        assert not any(" down" in c for c in commands) and not _deletes(commands)

    assert "this also stops the containers of MyApp" in result.output

    _, result = _destroy_with_data(monkeypatch, [], deployed=False, **shared)
    assert result.exit_code == 1
    assert "Nothing was destroyed" not in result.output
    assert "Once MyApp is destroyed too, --remove-data" in result.output

    commands, result = _destroy_with_data(monkeypatch, ["--keep-data"], **shared)
    assert result.exit_code == 0, result.output
    assert any(" down" in c for c in commands) and not _deletes(commands)

    commands, result = _destroy_with_data(
        monkeypatch, ["--remove-data", "--yes"], server_apps="myapp\nmyapp~\n"
    )
    assert result.exit_code == 0, result.output
    assert "docker volume rm myapp_redis_data" in _deletes(commands)


@pytest.mark.parametrize("update", [False, True])
def test_deploy_refuses_a_name_another_apps_compose_project_uses(update, capsys):
    executor = FakeExecutor({"caddy.d": "MyApp\nmyapp\n"})
    with pytest.raises(click.Abort):
        docker_ssh_module._check_compose_project_free(executor, "myapp", update)
    out = capsys.readouterr().out
    assert (
        "App name myapp gives the same Docker Compose project, myapp, as the "
        "existing app MyApp" in out
    )
    assert ("Destroy MyApp first with --keep-data;" in out) == update
    if update:
        with pytest.raises(click.Abort):
            docker_ssh_module._check_compose_project_free(
                FakeExecutor({"caddy.d": "MyApp\n"}), "myapp", update
            )
        out = capsys.readouterr().out
        assert "There is no app myapp to update; did you mean MyApp?" in out
    executor = FakeExecutor({"caddy.d": "myapp\nmyapp~\n"})
    docker_ssh_module._check_compose_project_free(executor, "myapp", update)


def test_stop_cloudflare_connector_quotes_the_app_name():
    executor = FakeExecutor({})
    docker_ssh_module._stop_cloudflare_connector(executor, "my app")
    assert executor.commands == [
        "docker compose -f ~/dallinger/'my app'/docker-compose.yml stop cloudflared"
    ]


def test_redis_volume_cleanup_uses_the_compose_project_name():
    executor = FakeExecutor({})
    docker_ssh_module.remove_redis_volumes("My.App", executor)
    assert executor.commands == ["docker volume rm 'myapp_redis_data'"]


def test_cloudflare_volume_cleanup_uses_the_compose_project_name():
    executor = FakeExecutor({})
    docker_ssh_module._remove_cloudflare_volumes("My.App", executor)
    assert executor.commands == [
        "docker volume rm 'myapp_redis_data'",
        "docker volume rm 'myapp_postgres_data'",
    ]


def test_destroy_rejects_shell_patterns_as_app_names(monkeypatch):
    with pytest.raises(click.UsageError):
        docker_ssh_module.destroy.callback(server="test-server", app="*")


def _fake_root_docker(tmp_path, ps_output="", ps_status=0):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "docker").write_text(
        f'#!/bin/bash\n[ "$1" = ps ] && {{ echo "{ps_output}"; exit {ps_status}; }}\n'
        'echo "$@" > "$HOME/docker-args"\n'
        'chmod u+w "$HOME/dallinger-data"; rm -rf "$HOME/dallinger-data/demo"\n'
    )
    (bin_dir / "docker").chmod(0o755)
    return LocalExecutor(tmp_path, bin_dir)


def test_remove_app_data_falls_back_to_a_root_container(tmp_path, capsys):
    data = tmp_path / "dallinger-data"
    (data / "demo" / "sub").mkdir(parents=True)
    (data / "other").mkdir()
    executor = _fake_root_docker(tmp_path)
    data.chmod(0o555)  # Stands in for the root-owned parent.
    try:
        docker_ssh_module._remove_app_data(executor, "demo")
    finally:
        data.chmod(0o755)
    assert not (data / "demo").exists() and (data / "other").exists()
    assert f"-v {data}:/data alpine:3.20 rm -rf /data/demo" in (
        (tmp_path / "docker-args").read_text()
    )
    assert "Deleted the folder ~/dallinger-data/demo.\n" in capsys.readouterr().out


@pytest.mark.parametrize(
    "ps_output, ps_status, warning",
    [
        ("abc123", 0, "its containers are still running"),
        ("", 1, "could not check whether its containers"),
    ],
)
def test_remove_data_refuses_unless_no_containers_run(
    tmp_path, capsys, ps_output, ps_status, warning
):
    (tmp_path / "dallinger-data" / "demo").mkdir(parents=True)
    executor = _fake_root_docker(tmp_path, ps_output, ps_status)
    item = ("folder", "~/dallinger-data/demo", "the folder ~/dallinger-data/demo")
    assert not docker_ssh_module._remove_experiment_data(executor, "demo", [item])
    assert (tmp_path / "dallinger-data" / "demo").exists()
    assert warning in capsys.readouterr().out


def test_remove_app_data_only_unlinks_a_symlink(tmp_path, capsys):
    target = tmp_path / "precious"
    target.mkdir()
    (tmp_path / "dallinger-data").mkdir()
    (tmp_path / "dallinger-data" / "demo").symlink_to(target)
    docker_ssh_module._remove_app_data(_fake_root_docker(tmp_path), "demo")
    assert not (tmp_path / "dallinger-data" / "demo").is_symlink()
    assert target.exists()
    assert f"its target {target} was kept" in capsys.readouterr().out


def test_update_removes_the_replaced_image_once_the_new_one_runs(capsys):
    old_compose = docker_ssh_module.get_docker_compose_yml({}, "myapp", "reg/exp:old")
    executor = FakeExecutor({"cat ~/dallinger/myapp/docker-compose.yml": old_compose})
    previous = docker_ssh_module._upload_app_stack(
        mock.Mock(),
        executor,
        {},
        app="myapp",
        server="s",
        public_origin="https://myapp.example",
        image_name="reg/exp:new",
        ingress="cloudflare",
        secrets={},
    )
    assert previous == "reg/exp:old"
    docker_ssh_module._remove_replaced_image(executor, "myapp", previous, "reg/exp:new")
    docker_ssh_module._remove_replaced_image(
        executor, "myapp", "reg/exp:new", "reg/exp:new"
    )
    rmis = [c for c in executor.commands if "docker rmi" in c]
    assert len(rmis) == 1 and "docker rmi reg/exp:old " in rmis[0]

    failing = mock.Mock()
    failing.run.side_effect = OSError("connection lost")
    docker_ssh_module._remove_replaced_image(failing, "myapp", previous, "reg/exp:new")
    assert "could not remove the previous image reg/exp:old" in (
        capsys.readouterr().out
    )


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


@pytest.mark.parametrize("auto_recruit, noticed", [("true", True), ("false", False)])
def test_compose_environment_notes_idle_sleep_waits_for_auto_recruit(
    capsys, auto_recruit, noticed
):
    config = mock.MagicMock()
    config.canonical_key.side_effect = lambda key: key
    config.as_dict.return_value = {}
    config.__getitem__.side_effect = {"aws_region": "x", "auto_recruit": False}.get
    docker_ssh_module._compose_environment(
        config,
        {"docker_ssh_idle_hibernate": "true", "auto_recruit": auto_recruit},
        "live",
        "uuid",
        "image:tag",
        "flask-key",
    )
    assert ("Idle sleep stays off" in capsys.readouterr().out) is noticed


def test_compose_environment_strips_cloudflare_api_token():
    class Config:
        synonyms = {"threads": "web_processes"}
        canonical_key = Configuration.canonical_key

        def is_set_explicitly(self, key):
            return False

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
            return default

        def __getitem__(self, key):
            return self.as_dict()[key]

    with pytest.warns(FutureWarning, match="'threads'"):
        env = docker_ssh_module._compose_environment(
            Config(),
            {
                "cloudflare_api_token": "from-cli",
                "host": "smuggled",
                "threads": "2",
            },
            "live",
            "uuid",
            "image:tag",
            "flask-key",
        )
    assert env["FLASK_SECRET_KEY"] == "flask-key"
    assert "cloudflare_api_token" not in env
    assert "from-cli" not in env.values()
    assert env["AWS_ACCESS_KEY_ID"] == "id"
    assert "host" not in env
    assert env["web_processes"] == "2"
    assert "threads" not in env


def test_compose_environment_falls_back_to_num_dynos_worker(stub_config):
    stub_config.extend({"num_dynos_worker": 3})
    with pytest.warns(FutureWarning, match="worker_processes"):
        env = docker_ssh_module._compose_environment(
            stub_config, {}, "live", "uuid", "image:tag", "flask-key"
        )
    assert env["worker_processes"] == 3


def test_deploy_validates_config_options_before_deploying(monkeypatch):
    config = Configuration()
    config._reset(register_defaults=True)
    config.ready = True
    monkeypatch.setattr(docker_ssh_module, "get_config", lambda load: config)
    monkeypatch.setattr(docker_ssh_module, "CONFIGURED_HOSTS", {"lab": {"host": "lab"}})
    monkeypatch.setattr(docker_ssh_module, "get_experiment_files", lambda path: None)
    monkeypatch.setattr(docker_ssh_module, "_ipv4_addresses", lambda host: [])
    checks = mock.Mock()
    monkeypatch.setattr(docker_ssh_module, "run_pre_launch_checks", checks)
    with pytest.raises(ValueError, match="non-negative"):
        docker_ssh_module._deploy_in_mode(
            **_deploy_kwargs(
                app_name="myapp",
                config_options=(("worker_processes", "-1"),),
                server="lab",
            )
        )
    checks.assert_not_called()


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
    # A socket pair stands in for the SSH channel; the far end echoes.
    channel, remote = socket.socketpair()
    executor.client.get_transport.return_value.open_channel.return_value = channel
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *a, **k: executor)

    with docker_ssh_module.remote_postgres(
        {"host": "example.com", "user": "ubuntu"}, "myapp"
    ) as uri:
        assert uri.startswith("postgresql://myapp:s3cret@127.0.0.1:")
        assert uri.endswith("/myapp")
        port = int(uri.rsplit(":", 1)[1].split("/")[0])
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            client.sendall(b"ping")
            remote.settimeout(5)
            remote.sendall(remote.recv(4))
            assert client.recv(4) == b"ping"

    open_channel = executor.client.get_transport.return_value.open_channel
    assert open_channel.call_args.args[:2] == ("direct-tcpip", ("10.0.0.8", 5432))
    executor.client.close.assert_not_called()
    remote.close()


def test_forward_local_port_drops_connection_when_server_refuses(caplog):
    transport = mock.Mock()
    transport.open_channel.side_effect = docker_ssh_module.paramiko.ChannelException(
        1, "Administratively prohibited"
    )
    with docker_ssh_module._forward_local_port(transport, ("10.0.0.8", 5432)) as port:
        with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
            assert client.recv(1) == b""
    assert "Could not open SSH tunnel to 10.0.0.8:5432" in caplog.text


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
    with pytest.raises(docker_ssh_module.ExecuteException, match="not running"):
        with docker_ssh_module.remote_postgres(
            {"host": "example.com", "user": "ubuntu"}, "myapp"
        ):
            pass
    executor.client.close.assert_not_called()


def test_select_running_app_returns_lone_hibernating_app(monkeypatch):
    monkeypatch.setattr(
        docker_ssh_module,
        "get_apps",
        lambda *args, **kwargs: [
            docker_ssh_module.App(name="asleep", state="hibernating")
        ],
    )

    assert docker_ssh_module.select_running_app("irrelevant") == "asleep"


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


def _fake_bin(tmp_path):
    """Fake ``docker`` (logs its arguments) and ``stat`` (a docker.sock group).

    ``docker image inspect`` fails for images listed in ``$HOME/absent-images``.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (
        (
            "docker",
            'echo "$@" >> "$HOME/docker.log"\n'
            '[ "$1 $2" = "image inspect" ] && '
            'grep -qxF -- "${@: -1}" "$HOME/absent-images" 2>/dev/null && exit 1\n'
            "exit 0",
        ),
        ("stat", "echo 999"),
    ):
        (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
        (bin_dir / name).chmod(0o755)
    return bin_dir


def test_update_wakes_a_hibernating_app(tmp_path, capsys):
    state = tmp_path / "dallinger" / "demo" / "state"
    state.mkdir(parents=True)
    (state / "hibernating").write_text("")
    executor = LocalExecutor(tmp_path, _fake_bin(tmp_path))
    docker_ssh_module._bring_up_app_containers(
        executor, {}, "demo", None, True, restore=False
    )
    assert not (state / "hibernating").exists()
    assert (state / "access.log").exists()
    log = (tmp_path / "docker.log").read_text()
    assert "demo/docker-compose.yml up -d" in log
    recreate_controller = log.index("--force-recreate controller")
    assert recreate_controller < log.index("demo/docker-compose.yml up -d\n")
    assert "--force-recreate frontdoor" in log
    assert "was hibernating. The update woke it." in capsys.readouterr().out


def test_classic_bring_up_does_not_restore_twice(monkeypatch):
    executor = mock.Mock()
    executor.run.return_value = ""
    monkeypatch.setattr(
        docker_ssh_module,
        "_restore_experiment_archive",
        mock.Mock(side_effect=AssertionError("classic already restored")),
    )
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


def test_start_server_services_waits_only_for_postgres():
    executor = mock.Mock()
    docker_ssh_module._start_server_services(executor)
    commands = [call.args[0] for call in executor.run.call_args_list]
    assert commands[0].endswith("docker-compose.yml up -d")
    assert commands[-1].startswith("timeout 420 ")
    assert "up -d --wait postgresql" in commands[-1]
    assert "--wait-timeout" not in commands[-1]


def test_postgres_wait_timeout_prints_server_stack_logs(capsys):
    executor = object.__new__(docker_ssh_module.Executor)
    executor.app, executor.host = "demo", "host"
    executor.run_with_status = mock.Mock(
        side_effect=[(0, "", ""), (124, "", "not healthy"), (0, "recovery log", "")]
    )
    with pytest.raises(docker_ssh_module.ExecuteException):
        docker_ssh_module._start_server_services(executor)
    assert executor.run_with_status.call_args.args[0].startswith(
        f"{docker_ssh_module.SERVER_COMPOSE} logs"
    )
    assert "recovery log" in capsys.readouterr().out


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
    assert f"UID={os.getuid()}\nGID={os.getgid()}\nDOCKER_GID=999\n" in env
    for sub in ("dallinger-data/demo", "dallinger/demo/state", "psynet-data/assets"):
        assert (tmp_path / sub).is_dir()
    assert not (tmp_path / "docker.log").exists()


def test_write_experiment_compose_env_reports_a_failed_chown(tmp_path, capsys):
    (tmp_path / "dallinger" / "demo").mkdir(parents=True)
    bin_dir = _fake_bin(tmp_path)
    for name in ("chown", "docker"):
        (bin_dir / name).write_text("#!/bin/bash\nexit 1\n")
        (bin_dir / name).chmod(0o755)
    docker_ssh_module._write_experiment_compose_env(
        LocalExecutor(tmp_path, bin_dir), "demo"
    )
    assert "Warning: could not chown" in capsys.readouterr().out


def test_update_reads_back_the_secrets_deploy_wrote(tmp_path, monkeypatch):
    (tmp_path / "dallinger" / "demo").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    executor = LocalExecutor(tmp_path)
    sftp = mock.Mock()
    sftp.putfo.side_effect = lambda data, path: (tmp_path / path).write_bytes(
        data.getvalue()
    )
    docker_ssh_module._write_app_env(
        sftp, executor, "demo", {"POSTGRES_PASSWORD": "pw", "FLASK_SECRET_KEY": "k"}
    )
    assert (tmp_path / "dallinger/demo/.env").stat().st_mode & 0o777 == 0o600
    read = docker_ssh_module._existing_app_secret
    assert read(executor, "demo", "FLASK_SECRET_KEY") == "k"
    assert read(executor, "demo", "POSTGRES_PASSWORD") == "pw"
    assert read(executor, "missing", "FLASK_SECRET_KEY") is None


def test_remote_bind_mount_dirs_only_chowns_writable_home_subdirs():
    dirs = docker_ssh_module._remote_bind_mount_dirs(
        "./dallinger.log:/experiment/dallinger.log,"
        "${HOME}/psynet-data/assets:/psynet-data/assets,"
        "/etc/ssl:/certs:ro,/srv/data:/data,~:/home,~/configs:/configs:ro",
        "consonance",
    )
    assert dirs == [
        '"$HOME/dallinger-data/$app"',
        '"$HOME/dallinger/$app/state"',
        '"$HOME/psynet-data/assets"',
    ]


def test_awaken_app_optional_when_compose_missing(monkeypatch):
    executor = mock.Mock()
    executor.run.return_value = ""
    monkeypatch.setattr(
        docker_ssh_module,
        "CONFIGURED_HOSTS",
        {"s.example.com": {"host": "s.example.com", "user": "ubuntu"}},
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
        if "state/hibernating" in cmd:
            return "/home/u/dallinger/demo/state/hibernating\n"
        if "config --services" in cmd:
            return "web\ncontroller\n"
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


def test_hibernate_explains_apps_without_a_front_door(monkeypatch, capsys):
    executor = FakeExecutor({"test -f": "Yes", "config --services": "web\nredis\n"})
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"s": {"host": "example.com"}}
    )
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *a, **k: executor)
    with pytest.raises(click.Abort):
        docker_ssh_module._run_hibernation_action("s", "demo", "hibernate")
    assert "redeploy it with --update" in capsys.readouterr().out
    assert not any("exec" in cmd for cmd in executor.commands)


def test_awaken_skips_an_app_that_is_already_awake(monkeypatch, capsys):
    executor = FakeExecutor({"test -f": "Yes"})
    monkeypatch.setattr(
        docker_ssh_module, "CONFIGURED_HOSTS", {"s": {"host": "example.com"}}
    )
    monkeypatch.setattr(docker_ssh_module, "Executor", lambda *a, **k: executor)
    assert docker_ssh_module.awaken_app("s", "demo", required=False) is True
    assert not any("exec" in cmd for cmd in executor.commands)
    assert capsys.readouterr().out == ""
    docker_ssh_module.awaken.callback(server="s", app="demo")
    assert capsys.readouterr().out == "App demo is awake\n"


def test_get_apps_reports_hibernation_from_markers():
    executor = FakeExecutor(
        {
            "for app in ": "",
            "caddy.d": "alpha\nbeta\n",
            "state/hibernating": "/home/test/dallinger/alpha/state/hibernating\n",
        }
    )
    with (
        mock.patch.object(docker_ssh_module, "_resolve_server_info", return_value={}),
        mock.patch.object(docker_ssh_module, "_build_executor", return_value=executor),
    ):
        apps = docker_ssh_module.get_apps("irrelevant")
    assert [(app.name, app.state) for app in apps] == [
        ("alpha", "hibernating"),
        ("beta", "inactive"),
    ]


def test_remote_hibernation_states_reads_marker_files(tmp_path):
    for app, marker in (("a", "hibernating"), ("b", "waking"), ("c", None)):
        state = tmp_path / "dallinger" / app / "state"
        state.mkdir(parents=True)
        if marker:
            (state / marker).write_text("")
    assert docker_ssh_module._remote_hibernation_states(LocalExecutor(tmp_path)) == {
        "a": "hibernating",
        "b": "waking",
    }


@pytest.mark.parametrize("label, expected", [("1\n", True), ("\n", False)])
def test_only_labelled_images_run_as_the_ssh_user(label, expected, capsys):
    executor = FakeExecutor({"image inspect": label})
    assert docker_ssh_module._image_runs_as_ssh_user(executor, "img:tag") is expected
    assert ("run as root" in capsys.readouterr().out) is not expected


@pytest.mark.parametrize(
    "image, present, pulled",
    [
        ("my-study:abc", True, False),
        ("my-study:abc", False, True),
        ("user/exp:abc", True, True),
        ("ghcr.io/u/exp:abc", True, True),
    ],
)
def test_only_registry_images_present_locally_are_pulled(
    tmp_path, image, present, pulled
):
    if not present:
        (tmp_path / "absent-images").write_text(f"{image}\n")
    executor = LocalExecutor(tmp_path, _fake_bin(tmp_path))
    docker_ssh_module._image_runs_as_ssh_user(executor, image)
    log = (tmp_path / "docker.log").read_text()
    assert (f"pull -q {image}" in log) is pulled
