"""Shared classic-ingress server files: written by setup and upgrade, never by deploys."""

import contextlib
import hashlib
import importlib
import io
import os
import re
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

    client = mock.Mock()

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
    for name in SERVER_FILES:
        assert (server / "dallinger" / name).stat().st_mode & 0o777 == 0o444
    assert (server / "dallinger/root.d").is_dir()
    assert "https://logs.lab.example.org (user = dallinger, password = " in (
        result.output
    )
    assert "up -d" in docker_calls(server)


def test_servers_upgrade_rewrites_server_files_and_keeps_backups(server):
    (server / "dallinger/.env.json").unlink()
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

    result = CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab"])
    assert result.exit_code == 0, result.output
    assert "files on lab.example.org are up to date." in result.output


@pytest.mark.parametrize(
    "app_name, hostname, route_dir, update",
    [
        ("myapp", "myapp.1.2.3.4.nip.io", "caddy.d", False),
        (None, "1.2.3.4.nip.io", "caddy.d", False),
        (None, "lab.example.org", "root.d", False),
        ("myapp", "myapp.1.2.3.4.nip.io", "root.d", True),
    ],
    ids=["subdomain", "own-host", "server-root", "update-server-root"],
)
def test_classic_deploy_only_writes_its_own_caddy_route(
    server, app_name, hostname, route_dir, update, capsys
):
    if route_dir == "root.d":
        CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"])
        (server / "docker.log").unlink()
    if update:
        (server / "dallinger/myapp").mkdir()
        (server / "dallinger/myapp/docker-compose.yml").write_text("services: {}\n")
        (server / "dallinger/root.d/myapp").write_text("old route\n")
    before = checksums(server)
    config = Configuration()
    config._reset(register_defaults=True)
    config.ready = True
    built_image = mock.Mock(return_value=contextlib.nullcontext("image"))
    with mock.patch.multiple(
        docker_ssh,
        get_config=lambda load=False: config,
        run_pre_launch_checks=mock.DEFAULT,
        _compose_environment=mock.Mock(return_value={}),
        _upload_app_stack=mock.DEFAULT,
        _bring_up_app_containers=mock.DEFAULT,
        _record_then_launch=mock.DEFAULT,
        get_server_pem_path=mock.Mock(return_value="key.pem"),
        get_experiment_files=mock.DEFAULT,
        _check_classic_ingress_reachable=mock.DEFAULT,
        _classic_preflight=mock.Mock(return_value=hostname),
        ensure_root_domain_ready=mock.DEFAULT,
        _built_image=built_image,
    ) as mocks:
        result = docker_ssh._deploy_in_mode(
            app_name=app_name,
            archive_path=None,
            config_options=(),
            dns_host="1.2.3.4.nip.io",
            mode="live",
            server="lab",
            update=update,
            local_build=False,
            push_build=False,
        )

    assert checksums(server) == before
    # Only an app that takes the server's own host replaces its other apps.
    assert mocks["ensure_root_domain_ready"].called == (hostname == "lab.example.org")
    # A failed new deploy removes the image it built; an update keeps it.
    assert built_image.call_args.kwargs["remove_on_error"] is not update
    routes = [
        p for d in ("caddy.d", "root.d") for p in (server / "dallinger" / d).glob("*")
    ]
    assert [p.parent.name for p in routes] == [route_dir]
    # root.d marks a server as set up, so a deploy must not create it.
    assert (server / "dallinger/root.d").exists() == (route_dir == "root.d")
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
    assert "another DNS name" not in output
    assert "older Dallinger" not in output


def test_server_check_suggests_saving_the_dns_host_the_server_serves(server, capsys):
    (server / "dallinger/Caddyfile").write_text(
        OLD_CADDYFILE.replace("lab.example.org", "other.example.org")
    )
    with (
        mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=["1.2.3.4"]),
        pytest.raises(click.Abort),
    ):
        docker_ssh._classic_preflight("lab", "myapp", None, None, False)
    output = capsys.readouterr().out
    assert "does not serve lab.example.org" in output
    assert "another DNS name, save that name with" in output


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


@pytest.mark.parametrize(
    "old_host, route, content",
    [
        ("lab.example.org", "root.d/old", "reverse_proxy old_web:5000\n"),
        (
            "1.2.3.4.nip.io",
            "caddy.d/old",
            "1.2.3.4.nip.io {\n    tls lab@example.org\n    reverse_proxy old_web:5000\n}",
        ),
    ],
    ids=["server-host", "other-dns-host"],
)
def test_upgrade_keeps_an_old_root_domain_app_at_its_address(
    server, old_host, route, content
):
    caddyfile = LEGACY_ROOT_CADDYFILE.replace("lab.example.org", old_host)
    (server / "dallinger/Caddyfile").write_text(caddyfile)
    (server / "dallinger/old").mkdir()
    (server / "dallinger/old/docker-compose.yml").write_text("services: {}\n")
    (server / "dallinger/docker-compose.yml").write_text("- DOZZLE_BASE=/logs\n")

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert (server / "dallinger" / route).read_text() == content
    assert "route files will be added" in result.output
    assert f"\n  ~/dallinger/{route}\n" in result.output
    assert (
        "log viewer moves from the /logs path to https://logs.lab.example.org,"
        in result.output
    )


def test_server_check_accepts_a_site_with_several_addresses(server):
    caddyfile = server / "dallinger/Caddyfile"
    caddyfile.write_text(
        caddyfile.read_text().replace(
            "lab.example.org {", "https://lab.example.org, www.lab.example.org {", 1
        )
    )
    with mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=["1.2.3.4"]):
        docker_ssh._classic_preflight("lab", "myapp", None, None, False)


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


def test_servers_add_accepts_a_set_up_ip_server_without_a_dns_host(server, monkeypatch):
    monkeypatch.setattr(docker_ssh, "get_configured_hosts", lambda: {})
    monkeypatch.setattr(docker_ssh, "_config_contact_email", lambda: None)
    with (
        mock.patch.object(docker_ssh, "prepare_server"),
        mock.patch.object(docker_ssh, "store_host"),
    ):
        result = CliRunner().invoke(docker_ssh.servers, ["add", "--host", "1.2.3.4"])

    assert result.exit_code == 0, result.output
    assert "left unchanged" in result.output


def test_a_root_route_occupies_the_app_name(server):
    (server / "dallinger/root.d").mkdir()
    (server / "dallinger/root.d/myapp").write_text("reverse_proxy myapp_web:5000\n")

    with pytest.raises(click.Abort):
        docker_ssh._check_app_slot(LocalExecutor(server), "myapp", False, "classic")


def test_servers_add_needs_a_dns_host_to_set_up_a_fresh_ip_server(server, monkeypatch):
    (server / "dallinger/docker-compose.yml").unlink()
    monkeypatch.setattr(docker_ssh, "get_configured_hosts", lambda: {})
    monkeypatch.setattr(docker_ssh, "_config_contact_email", lambda: None)
    with (
        mock.patch.object(docker_ssh, "prepare_server"),
        mock.patch.object(docker_ssh, "store_host"),
    ):
        result = CliRunner().invoke(docker_ssh.servers, ["add", "--host", "1.2.3.4"])

    assert result.exit_code == 1
    assert "servers add --host 1.2.3.4" in result.output
    assert "to the deploy" not in result.output
    assert not (server / "dallinger/docker-compose.yml").exists()


def test_destroy_removes_a_root_route_but_not_the_server_files(server):
    CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"])
    (server / "dallinger/root.d/myapp").write_text("reverse_proxy myapp_web:5000\n")
    (server / "dallinger/myapp").mkdir()
    (server / "dallinger/myapp/docker-compose.yml").write_text("services: {}\n")
    before = checksums(server)

    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert checksums(server) == before
    assert not (server / "dallinger/root.d/myapp").exists()


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write read-only files")
def test_upgrade_leaves_the_server_files_read_only_for_older_dallinger(
    server, monkeypatch
):
    CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"])
    before = checksums(server)

    # Older Dallinger rewrites these files with sftp.putfo, which opens them for writing.
    for name in SERVER_FILES:
        path = server / "dallinger" / name
        assert path.stat().st_mode & 0o777 == 0o444
        with pytest.raises(PermissionError):
            LocalSftp(server).putfo(io.BytesIO(b"old"), f"dallinger/{name}")
    assert checksums(server) == before

    monkeypatch.setitem(SERVER, "contact_email", "new@example.org")
    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(
        docker_ssh.docker_ssh,
        ["set-dozzle-password", "--server", "lab", "--password", "pw2"],
    )
    assert result.exit_code == 0, result.output
    assert "tls new@example.org" in (server / "dallinger/Caddyfile").read_text()
    assert "pw2" in (server / "dallinger/.env.json").read_text()
    for name in SERVER_FILES:
        assert (server / "dallinger" / name).stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize(
    "old_compose", [True, False], ids=["old-deploy", "old-root-destroy"]
)
def test_deploy_refuses_a_set_up_server_that_older_dallinger_rewrote(
    server, old_compose, capsys
):
    CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"])
    # What an older Dallinger writes, on a server it could still write to: a
    # deploy rewrites both files, a root-domain destroy only the Caddyfile.
    compose = server / "dallinger/docker-compose.yml"
    rewrites = {"Caddyfile": OLD_CADDYFILE}
    if old_compose:
        rewrites[compose.name] = re.sub(
            r" *- (\./root\.d|caddy_data):.*\n", "", compose.read_text()
        )
    for name, content in rewrites.items():
        (server / "dallinger" / name).chmod(0o644)
        (server / "dallinger" / name).write_text(content)
    (server / "dallinger/old").mkdir()
    (server / "dallinger/old/docker-compose.yml").write_text("services: {}\n")
    before = checksums(server)
    (server / "docker.log").unlink()

    with (
        mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=["1.2.3.4"]),
        pytest.raises(click.Abort),
    ):
        docker_ssh._classic_preflight("lab", "myapp", None, None, False)
    output = capsys.readouterr().out
    assert "An older Dallinger version has rewritten the shared files" in output
    assert "dallinger docker-ssh servers upgrade --host lab.example.org" in output
    assert ("duplicate certificates" in output) == old_compose
    assert "up -d" not in docker_calls(server)

    docker_ssh.destroy.callback(server="lab", app="old")
    output = capsys.readouterr().out
    assert "Warning: " in output
    assert "An older Dallinger version has rewritten the shared files" in output
    assert not (server / "dallinger/old").exists()
    assert checksums(server) == before

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )
    assert "An older Dallinger version has rewritten these files" in result.output
    with mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=["1.2.3.4"]):
        docker_ssh._classic_preflight("lab", "myapp", None, None, False)


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write read-only files")
def test_a_failed_upgrade_leaves_the_server_files_read_only(server, monkeypatch):
    CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"])
    monkeypatch.setitem(SERVER, "contact_email", "new@example.org")

    class FailingSftp(LocalSftp):
        def putfo(self, fo, path):
            if path == "dallinger/Caddyfile":
                raise OSError("connection lost")
            super().putfo(fo, path)

    monkeypatch.setattr(docker_ssh, "get_sftp", lambda *a, **k: FailingSftp(server))
    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert isinstance(result.exception, OSError)
    assert "tls lab@example.org" in (server / "dallinger/Caddyfile").read_text()
    for name in SERVER_FILES:
        assert (server / "dallinger" / name).stat().st_mode & 0o777 == 0o444


@pytest.mark.parametrize("dns_host", ["exp.example.org", None])
def test_ec2_provision_sets_up_the_shared_services(
    server, dns_host, monkeypatch, capsys
):
    ec2 = importlib.import_module("dallinger.command_line.lib.ec2")
    for name in SERVER_FILES:
        (server / "dallinger" / name).unlink()
    stored, ssh_hosts = [], []
    executor = LocalExecutor(server)
    monkeypatch.setattr(
        docker_ssh, "Executor", lambda host, *a, **k: ssh_hosts.append(host) or executor
    )
    monkeypatch.setattr(
        docker_ssh,
        "get_sftp",
        lambda host, **k: ssh_hosts.append(host) or LocalSftp(server),
    )
    monkeypatch.setattr(docker_ssh, "get_configured_hosts", lambda: {})
    monkeypatch.setattr(docker_ssh, "_config_contact_email", lambda: "me@example.org")
    # Inside AWS, the AWS hostname can resolve to the private IP.
    monkeypatch.setattr(docker_ssh, "gethostbyname_ex", lambda h: (h, [], ["10.0.0.5"]))
    monkeypatch.setattr(docker_ssh, "store_host", stored.append)
    monkeypatch.setattr(ec2, "dallinger_store_host", stored.append)
    monkeypatch.setattr(ec2, "dallinger_prepare_server", mock.Mock())
    monkeypatch.setattr(ec2, "create_dns_records", mock.Mock())
    config = Configuration()
    config._reset(register_defaults=True)
    config.extend({"dashboard_user": "admin", "dashboard_password": "pw"})
    config.ready = True
    monkeypatch.setattr("dallinger.config.get_config", lambda load=False: config)

    aws_host = "ec2-1-2-3-4.compute.amazonaws.com"
    ec2.prepare_docker_experiment_setup(
        aws_host, "ubuntu", "1.2.3.4", None, dns_host=dns_host
    )

    # A new DNS record may still resolve to an older server.
    assert set(ssh_hosts) == {aws_host}
    record = {
        "host": aws_host,
        "user": "ubuntu",
        "default_ingress": "classic",
        "dns_host": dns_host or "1.2.3.4.nip.io",
        "contact_email": "me@example.org",
    }
    assert stored == [record] + ([{**record, "host": dns_host}] if dns_host else [])
    site = dns_host or "1.2.3.4.nip.io"
    assert f"logs.{site} {{" in (server / "dallinger/Caddyfile").read_text()
    for name in SERVER_FILES:
        assert (server / "dallinger" / name).stat().st_mode & 0o777 == 0o444
    assert capsys.readouterr().out.count("password = ") == 1
    assert "up -d" in docker_calls(server)
