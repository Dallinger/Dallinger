"""Shared classic-ingress server files: written by setup and upgrade, never by deploys."""

import hashlib
import importlib
import subprocess
from unittest import mock

import click
import pytest
from click.testing import CliRunner

from dallinger.config import Configuration

docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")

SERVER = {
    "host": "lab.example.org",
    "user": "me",
    "default_ingress": "classic",
    "contact_email": "lab@example.org",
}
SERVER_FILES = ("Caddyfile", "docker-compose.yml", "dozzle-users.yml", ".env.json")
# A server set up by an older Dallinger and then edited by hand.
OLD_CADDYFILE = """lab.example.org {
    respond /health-check 200
    tls lab@example.org
}

logs.lab.example.org {
    reverse_proxy dozzle:8080
    tls lab@example.org
}

import caddy.d/*
"""
FAKE_DOCKER = """#!/bin/sh
echo "$*" >> "$HOME/docker.log"
case "$*" in *"ps --services"*) printf 'httpserver\\npostgresql\\ndozzle\\n';; esac
"""


class LocalExecutor(docker_ssh.Executor):
    """Run the server's commands with bash in ``home``, with a fake ``docker``."""

    def __init__(self, home):
        self.home, self.app, self.host = home, None, SERVER["host"]

    def run_with_status(self, cmd):
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True,
            text=True,
            env={"HOME": str(self.home), "PATH": f"{self.home}/bin:/usr/bin:/bin"},
        )
        return result.returncode, result.stdout, result.stderr


class LocalSftp:
    def __init__(self, home):
        self.home = home

    def putfo(self, fo, path):
        (self.home / path).write_bytes(fo.read())

    def chmod(self, path, mode):
        pass


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A fake server home already set up for classic ingress."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, script in (("docker", FAKE_DOCKER), ("timeout", 'shift; "$@"\n')):
        (bin_dir / name).write_text(
            script if name == "docker" else f"#!/bin/sh\n{script}"
        )
        (bin_dir / name).chmod(0o755)
    dallinger_dir = tmp_path / "dallinger"
    (dallinger_dir / "caddy.d").mkdir(parents=True)
    (dallinger_dir / "Caddyfile").write_text(OLD_CADDYFILE)
    (dallinger_dir / "docker-compose.yml").write_text("services: {}  # edited\n")
    (dallinger_dir / "dozzle-users.yml").write_text("users: {}\n")
    (dallinger_dir / ".env.json").write_text('{"DOZZLE_PASSWORD": "pw"}')
    executor = LocalExecutor(tmp_path)
    monkeypatch.setattr(docker_ssh, "Executor", lambda *args, **kwargs: executor)
    monkeypatch.setattr(docker_ssh, "get_sftp", lambda *a, **k: LocalSftp(tmp_path))
    hosts = {SERVER["host"]: SERVER}
    monkeypatch.setattr(docker_ssh, "get_configured_hosts", lambda: hosts)
    monkeypatch.setattr(docker_ssh, "CONFIGURED_HOSTS", hosts)
    return tmp_path


def checksums(home):
    return {
        name: hashlib.sha256((home / "dallinger" / name).read_bytes()).hexdigest()
        for name in SERVER_FILES
    }


def docker_calls(home):
    log = home / "docker.log"
    return log.read_text() if log.exists() else ""


def test_servers_add_sets_up_a_fresh_server_but_leaves_a_set_up_one(server):
    with (
        mock.patch.object(docker_ssh, "prepare_server"),
        mock.patch.object(docker_ssh, "store_host"),
    ):
        before = checksums(server)
        result = CliRunner().invoke(
            docker_ssh.servers, ["add", "--host", "lab.example.org"]
        )
        assert result.exit_code == 0, result.output
        assert checksums(server) == before
        assert docker_calls(server) == ""
        assert "servers upgrade --host lab.example.org" in result.output

        for name in SERVER_FILES:
            (server / "dallinger" / name).unlink()
        result = CliRunner().invoke(
            docker_ssh.servers, ["add", "--host", "lab.example.org"]
        )

    assert result.exit_code == 0, result.output
    caddyfile = (server / "dallinger" / "Caddyfile").read_text()
    assert "logs.lab.example.org {" in caddyfile
    assert "tls lab@example.org" in caddyfile
    assert "caddy_data:/data" in (server / "dallinger/docker-compose.yml").read_text()
    assert "https://logs.lab.example.org (user = dallinger, password = " in (
        result.output
    )
    assert "up -d" in docker_calls(server)


def test_servers_upgrade_rewrites_server_files_and_keeps_backups(server):
    result = CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab"])
    assert result.exit_code == 1
    assert (server / "dallinger/Caddyfile").read_text() == OLD_CADDYFILE

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert "~/dallinger/Caddyfile" in result.output
    assert "import root.d/*" in (server / "dallinger/Caddyfile").read_text()
    backups = sorted(p.name for p in (server / "dallinger").glob("*.bak"))
    assert [name.split(".")[0] for name in backups] == ["Caddyfile", "docker-compose"]
    assert (server / "dallinger/dozzle-users.yml").read_text() == "users: {}\n"
    assert "up -d --wait postgresql" in docker_calls(server)
    assert "caddy reload" in docker_calls(server)


@pytest.mark.parametrize(
    "app_name, hostname, route_dir",
    [
        ("myapp", "myapp.1.2.3.4.nip.io", "caddy.d"),
        (None, "1.2.3.4.nip.io", "caddy.d"),
        (None, "lab.example.org", "root.d"),
    ],
    ids=["subdomain", "own-host", "server-root"],
)
def test_classic_deploy_only_writes_its_own_caddy_route(
    server, app_name, hostname, route_dir, capsys
):
    if route_dir == "root.d":
        CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"])
        (server / "docker.log").unlink()
    before = checksums(server)
    config = Configuration()
    config._reset(register_defaults=True)
    config.ready = True
    with mock.patch.multiple(
        docker_ssh,
        get_config=lambda load=False: config,
        run_pre_launch_checks=mock.DEFAULT,
        _compose_environment=mock.Mock(return_value={}),
        _upload_app_stack=mock.DEFAULT,
        _bring_up_app_containers=mock.DEFAULT,
        _record_then_launch=mock.DEFAULT,
    ):
        result = docker_ssh._deploy_in_mode(
            app_name=app_name,
            archive_path=None,
            config_options=(),
            dns_host="1.2.3.4.nip.io",
            image_name="image",
            mode="live",
            server="lab",
            update=False,
            local_build=False,
            push_build=False,
            preflight_root_clean=True,
            classic_hostname=hostname,
        )

    assert checksums(server) == before
    routes = [
        p for d in ("caddy.d", "root.d") for p in (server / "dallinger" / d).glob("*")
    ]
    assert [p.parent.name for p in routes] == [route_dir]
    assert f"reverse_proxy {result['app']}_web:5000" in routes[0].read_text()
    assert "up -d" not in docker_calls(server)
    assert "restart" not in docker_calls(server)
    assert "caddy reload" in docker_calls(server)
    assert "go to https://logs.lab.example.org (user = dallinger" in (
        capsys.readouterr().out
    )


@pytest.mark.parametrize(
    "app_name, remove, problem",
    [
        ("myapp", None, None),
        ("myapp", "docker-compose.yml", "has no ~/dallinger/docker-compose.yml"),
        (None, None, "cannot route lab.example.org to an app"),
    ],
    ids=["set-up", "not-set-up", "root-on-old-layout"],
)
def test_classic_deploy_checks_the_server_setup_before_building(
    server, app_name, remove, problem, capsys
):
    if remove:
        (server / "dallinger" / remove).unlink()
    with mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=["1.2.3.4"]):
        if problem is None:
            docker_ssh._classic_preflight("lab", app_name, None, None, False)
            return
        with pytest.raises(click.Abort):
            docker_ssh._classic_preflight("lab", app_name, None, None, False)
    output = capsys.readouterr().out
    assert problem in output
    assert "dallinger docker-ssh servers upgrade --host lab.example.org" in output


LEGACY_ROOT_CADDYFILE = """lab.example.org {
    tls lab@example.org
    handle /logs* {
        reverse_proxy dozzle:8080
    }
    handle {
        reverse_proxy old_web:5000
    }
}
"""


def test_upgrade_keeps_an_old_root_domain_app_reachable(server):
    (server / "dallinger/Caddyfile").write_text(LEGACY_ROOT_CADDYFILE)
    (server / "dallinger/old").mkdir()
    (server / "dallinger/old/docker-compose.yml").write_text("services: {}\n")

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert (server / "dallinger/root.d/old").read_text() == (
        "reverse_proxy old_web:5000\n"
    )


def test_destroy_leaves_an_old_root_domain_caddyfile_alone(server, capsys):
    (server / "dallinger/Caddyfile").write_text(LEGACY_ROOT_CADDYFILE)
    (server / "dallinger/old").mkdir()
    (server / "dallinger/old/docker-compose.yml").write_text("services: {}\n")
    before = checksums(server)

    docker_ssh.destroy.callback(server="lab", app="old")

    assert checksums(server) == before
    assert not (server / "dallinger/old").exists()
    assert "servers upgrade --host lab" in capsys.readouterr().out


def test_ip_server_without_a_saved_dns_host_uses_the_deploy_dns_host(
    server, monkeypatch, capsys
):
    ip_server = {**SERVER, "host": "1.2.3.4"}
    monkeypatch.setattr(docker_ssh, "CONFIGURED_HOSTS", {"1.2.3.4": ip_server})
    monkeypatch.setattr(docker_ssh, "_ipv4_addresses", lambda host: ["1.2.3.4"])
    caddyfile = server / "dallinger/Caddyfile"
    caddyfile.write_text(OLD_CADDYFILE.replace("lab.example.org", "1.2.3.4.nip.io"))

    with pytest.raises(click.Abort):
        docker_ssh._classic_preflight("1.2.3.4", "myapp", None, None, False)
    assert "or pass --dns-host <name> to the deploy" in capsys.readouterr().out

    assert (
        docker_ssh._classic_preflight("1.2.3.4", "myapp", None, "nip.io", False)
        == "myapp.1.2.3.4.nip.io"
    )
    assert docker_ssh._logs_url(ip_server, "nip.io") == "https://logs.1.2.3.4.nip.io"
