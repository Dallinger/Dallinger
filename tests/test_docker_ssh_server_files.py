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
[ -z "${pw:-}" ] || echo "environment pw=$pw" >> "$HOME/docker.log"
case "$*" in
  *"/dallinger/docker-compose.yml ps --services"*)
    printf 'httpserver\\npostgresql\\ndozzle\\n';;
MORE_CASES
esac
exit 0
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


def set_up_server(tmp_path, monkeypatch, docker_cases=""):
    """Make ``tmp_path`` a fake server home already set up for classic ingress.

    ``docker_cases`` adds ``case`` branches to the fake ``docker``.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = FAKE_DOCKER.replace("MORE_CASES\n", docker_cases)
    for name, script in (("docker", docker), ("timeout", 'shift; "$@"\n')):
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


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A fake server home already set up for classic ingress."""
    return set_up_server(tmp_path, monkeypatch)


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
            docker_ssh.servers,
            ["add", "--host", "lab.example.org", "--contact-email", "new@example.org"],
        )
        assert result.exit_code == 0, result.output
        assert checksums(server) == before
        assert docker_calls(server) == ""
        assert "servers upgrade --host lab.example.org" in result.output
        assert "new@example.org (from --contact-email), saved with the server" in (
            result.output
        )
        result = CliRunner().invoke(
            docker_ssh.servers, ["add", "--host", "lab.example.org"]
        )
        assert (
            "Let's Encrypt contact email: lab@example.org "
            "(from the saved server record)." in result.output
        )

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


def test_servers_upgrade_saves_a_given_contact_email(server, monkeypatch):
    saved = {key: value for key, value in SERVER.items() if key != "contact_email"}
    monkeypatch.setattr(docker_ssh, "get_configured_hosts", lambda: {"lab": saved})
    monkeypatch.setattr(docker_ssh, "_config_contact_email", lambda *a: (None, None))
    store_host = mock.Mock()
    monkeypatch.setattr(docker_ssh, "store_host", store_host)
    upgrade = ["upgrade", "--host", "lab", "--yes"]

    result = CliRunner().invoke(docker_ssh.servers, upgrade)
    assert result.exit_code == 1
    assert "servers upgrade --host lab --contact-email <email>" in result.output

    # Declining the upgrade saves nothing.
    result = CliRunner().invoke(
        docker_ssh.servers,
        ["upgrade", "--host", "lab", "--contact-email", "new@example.org"],
        input="n\n",
    )
    assert result.exit_code == 1
    assert "Let's Encrypt contact email" not in result.output
    store_host.assert_not_called()

    result = CliRunner().invoke(
        docker_ssh.servers, upgrade + ["--contact-email", "new@example.org"]
    )
    assert result.exit_code == 0, result.output
    assert store_host.call_args.args[0]["contact_email"] == "new@example.org"
    assert (
        "Let's Encrypt contact email: new@example.org (from --contact-email)."
        in result.output
    )
    assert "tls new@example.org" in (server / "dallinger/Caddyfile").read_text()


def test_a_dns_host_in_another_case_is_the_servers_host():
    hostname = docker_ssh._classic_hostname(SERVER, None, None, "Lab.example.org")
    assert hostname == "lab.example.org"


@pytest.mark.parametrize(
    "app_name, dns_host, hostname, route_dir, update",
    [
        ("myapp", "1.2.3.4.nip.io", "myapp.1.2.3.4.nip.io", "caddy.d", False),
        (None, "1.2.3.4.nip.io", "1.2.3.4.nip.io", "caddy.d", False),
        (None, None, "lab.example.org", "root.d", False),
        (None, "LAB.example.org", "lab.example.org", "root.d", False),
        ("myapp", None, "lab.example.org", "root.d", True),
        ("myapp", None, "myapp.lab.example.org", "caddy.d", True),
    ],
    ids=[
        "subdomain",
        "own-host",
        "server-root",
        "server-root-case",
        "update-root",
        "update-subdomain",
    ],
)
def test_classic_deploy_only_writes_its_own_caddy_route(
    server, app_name, dns_host, hostname, route_dir, update, capsys
):
    if route_dir == "root.d":
        CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"])
        (server / "docker.log").unlink()
    if update:
        (server / "dallinger/myapp").mkdir()
        (server / "dallinger/myapp/docker-compose.yml").write_text("services: {}\n")
        (server / "dallinger" / route_dir / "myapp").write_text("old route\n")
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
        # Only the app's hostname and the SSH host resolve.
        _ipv4_addresses=lambda name: (
            ["1.2.3.4"] if name in {hostname, SERVER["host"]} else []
        ),
        ensure_root_domain_ready=mock.DEFAULT,
        _built_image=built_image,
    ) as mocks:
        result = docker_ssh._deploy_in_mode(
            app_name=app_name,
            archive_path=None,
            config_options=(),
            dns_host=dns_host,
            mode="live",
            server="lab",
            update=update,
            local_build=False,
            push_build=False,
        )

    assert checksums(server) == before
    # Only an app that takes the server's own host replaces its other apps.
    assert mocks["ensure_root_domain_ready"].called == (
        route_dir == "root.d" and not update
    )
    # A failed new deploy removes the image it built; an update keeps it.
    assert built_image.call_args.kwargs["remove_for_app"] == (
        None if update else result["app"]
    )
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
    "app_name, dns_host, remove, problem",
    [
        ("myapp", None, None, None),
        ("myapp", None, "docker-compose.yml", "has no ~/dallinger/docker-compose.yml"),
        (None, None, None, "cannot route lab.example.org to an app"),
        (None, "Lab.example.org", None, "cannot route lab.example.org to an app"),
    ],
    ids=["set-up", "not-set-up", "root-on-old-layout", "root-in-another-case"],
)
def test_classic_deploy_checks_the_server_setup_before_building(
    server, app_name, dns_host, remove, problem, capsys
):
    if remove:
        (server / "dallinger" / remove).unlink()
    with mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=["1.2.3.4"]):
        if problem is None:
            docker_ssh._classic_preflight("lab", app_name, None, dns_host, False)
            return
        with pytest.raises(click.Abort):
            docker_ssh._classic_preflight("lab", app_name, None, dns_host, False)
    output = capsys.readouterr().out
    assert problem in output
    assert "dallinger docker-ssh servers upgrade --host lab.example.org" in output
    assert "another DNS name" not in output
    assert "older Dallinger" not in output


@pytest.mark.parametrize("update", [True, False], ids=["update", "new"])
def test_classic_deploy_stops_if_the_server_cannot_say_where_the_app_is(server, update):
    (server / "dallinger/myapp").mkdir()
    (server / "dallinger/myapp/docker-compose.yml").write_text("services: {}\n")
    (server / "dallinger/root.d").write_text("")  # not a searchable directory
    with pytest.raises(click.ClickException, match="Could not check whether myapp"):
        docker_ssh._classic_preflight("lab", "myapp", None, None, False, update)


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
        ("LAB.example.org", "root.d/old", "reverse_proxy old_web:5000\n"),
        (
            "1.2.3.4.nip.io",
            "caddy.d/old",
            "1.2.3.4.nip.io {\n    tls lab@example.org\n    reverse_proxy old_web:5000\n}",
        ),
    ],
    ids=["server-host", "server-host-other-case", "other-dns-host"],
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


def test_a_retried_upgrade_keeps_an_old_root_domain_app(server, monkeypatch):
    (server / "dallinger/Caddyfile").write_text(LEGACY_ROOT_CADDYFILE)
    (server / "dallinger/old").mkdir()
    (server / "dallinger/old/docker-compose.yml").write_text("services: {}\n")

    class FailingSftp(LocalSftp):
        def putfo(self, fo, path):
            if path == "dallinger/root.d/old":
                raise OSError("connection lost")
            super().putfo(fo, path)

    monkeypatch.setattr(docker_ssh, "get_sftp", lambda *a, **k: FailingSftp(server))
    upgrade = ["upgrade", "--host", "lab", "--yes"]
    assert isinstance(
        CliRunner().invoke(docker_ssh.servers, upgrade).exception, OSError
    )
    monkeypatch.setattr(docker_ssh, "get_sftp", lambda *a, **k: LocalSftp(server))
    result = CliRunner().invoke(docker_ssh.servers, upgrade)

    assert result.exit_code == 0, result.output
    assert (server / "dallinger/root.d/old").read_text() == (
        "reverse_proxy old_web:5000\n"
    )


def test_upgrade_refuses_a_server_with_an_old_app_called_root_d(server):
    (server / "dallinger/root.d").mkdir()
    (server / "dallinger/root.d/docker-compose.yml").write_text("services: {}\n")
    before = checksums(server)

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 1
    assert "destroy --server lab.example.org --app root.d" in result.output
    assert checksums(server) == before
    assert docker_calls(server) == ""


def test_a_new_deploy_without_app_checks_dns_before_connecting(server, monkeypatch):
    monkeypatch.setattr(docker_ssh, "Executor", mock.Mock(side_effect=AssertionError))
    with (
        mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=[]),
        pytest.raises(click.Abort),
    ):
        docker_ssh._classic_preflight("lab", None, None, None, False)


def test_server_check_accepts_a_site_with_several_addresses(server):
    caddyfile = server / "dallinger/Caddyfile"
    caddyfile.write_text(
        caddyfile.read_text().replace(
            "lab.example.org {", "https://lab.example.org, www.lab.example.org {", 1
        )
    )
    with mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=["1.2.3.4"]):
        docker_ssh._classic_preflight("lab", "myapp", None, None, False)


def test_deploy_refuses_a_hostname_another_app_serves(server, capsys):
    (server / "dallinger/caddy.d/exp").write_text(
        "https://Exp.example.org:443, www.exp.example.org {\n"
        "    tls lab@example.org\n    reverse_proxy exp_web:5000\n}"
    )
    with mock.patch.object(docker_ssh, "_ipv4_addresses", return_value=["1.2.3.4"]):
        with pytest.raises(click.Abort):
            docker_ssh._classic_preflight("lab", None, None, "exp.example.org", False)
        output = capsys.readouterr().out
        assert "exp.example.org is already served by exp" in output
        assert "dallinger docker-ssh destroy --app exp --server lab.example.org" in (
            output
        )
        # The app that serves it can be redeployed there.
        docker_ssh._classic_preflight("lab", "exp", None, "example.org", False)
        with pytest.raises(click.Abort):
            docker_ssh._classic_preflight("lab", "logs", None, None, False)
        assert (
            "logs.lab.example.org is the server's log viewer" in capsys.readouterr().out
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


class FakeBuildCache:
    """A daemon's build cache records (id to parent).

    A prune keeps a parent, and records an image shares (``shared``).
    """

    def __init__(self, records, home):
        self.records, self.home, self.api, self.shared = records, home, self, set()

    def prune_builds(self, filters):
        # The daemon prunes every unused record whose id matches the expression.
        deleted = [
            i
            for i in self.records
            if re.search(filters["id"], i)
            and i not in self.shared
            and i not in self.records.values()
        ]
        for cache_id in deleted:
            del self.records[cache_id]
        return {
            "CachesDeleted": deleted or None,
            "SpaceReclaimed": 1_500_000_000 * len(deleted),
        }

    def build(self, app, layers):
        before = list(self.records)
        self.records.update(layers)
        docker_ssh._record_build_cache(self, "lab", app, before)
        (self.home / "dallinger" / app / "docker-compose.yml").write_text(
            "services: {}\n"
        )


@pytest.fixture
def build_cache(server, monkeypatch):
    """A base image pulled earlier, and a layer another app's build added on it."""
    cache = FakeBuildCache({"base": None, "other": "base"}, server)
    monkeypatch.setattr(docker_ssh, "_build_cache_ids", lambda c: list(c.records))
    monkeypatch.setattr(
        docker_ssh,
        "_image_docker_client",
        lambda *a, **k: contextlib.nullcontext(cache),
    )
    return cache


def test_destroy_removes_only_the_build_cache_of_the_apps_builds(build_cache, capsys):
    # A deploy of myapp, then an update that reuses the deploy's dependencies.
    build_cache.build("myapp", {"deps": "base", "code1": "deps"})
    build_cache.build("myapp", {"code2": "deps"})

    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert list(build_cache.records) == ["base", "other"]
    assert "Removed the build cache of myapp (4.5 GB)." in capsys.readouterr().out


def test_a_later_destroy_removes_build_cache_an_image_kept(build_cache, server, capsys):
    build_cache.build("app1", {"deps": "base", "code1": "deps"})
    build_cache.build("app2", {"code2": "deps"})
    build_cache.shared = {"deps", "code2"}  # app2's image uses them

    docker_ssh.destroy.callback(server="lab", app="app1")
    assert (server / "dallinger/build-cache-leftovers").read_text() == "deps\n"

    build_cache.shared = set()
    docker_ssh.destroy.callback(server="lab", app="app2")
    assert list(build_cache.records) == ["base", "other"]
    assert not (server / "dallinger/build-cache-leftovers").exists()
    assert "Removed the build cache of app2 and build cache left by earlier " in (
        capsys.readouterr().out
    )


def test_destroy_carries_on_when_the_build_cache_cant_be_pruned(
    build_cache, server, capsys
):
    build_cache.build("myapp", {"deps": "base"})
    build_cache.prune_builds = mock.Mock(side_effect=RuntimeError("daemon busy"))

    docker_ssh.destroy.callback(server="lab", app="myapp")

    out = capsys.readouterr().out
    assert "Warning: could not remove build cache deps: daemon busy" in out
    assert "App myapp removed." in out
    assert not (server / "dallinger/myapp").exists()
    assert (server / "dallinger/build-cache-leftovers").read_text() == "deps\n"


def test_destroy_keeps_the_record_when_the_build_cache_cant_be_listed(
    build_cache, server, monkeypatch, capsys
):
    build_cache.build("myapp", {"deps": "base", "code": "deps"})
    monkeypatch.setattr(
        docker_ssh, "_build_cache_ids", mock.Mock(side_effect=RuntimeError("down"))
    )

    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert "could not remove the build cache of myapp: down" in capsys.readouterr().out
    leftovers = server / "dallinger/build-cache-leftovers"
    assert leftovers.read_text() == "code\ndeps\n"


def test_destroy_of_an_app_without_a_record_leaves_the_build_cache(
    build_cache, server, capsys
):
    (server / "dallinger/myapp").mkdir()
    (server / "dallinger/myapp/docker-compose.yml").write_text("services: {}\n")
    build_cache.records["deps"] = "base"

    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert list(build_cache.records) == ["base", "other", "deps"]
    assert "App myapp removed." in capsys.readouterr().out


def test_destroy_prunes_only_the_exact_recorded_id(build_cache, server):
    build_cache.build("app1", {"ab": "base"})
    build_cache.build("app2", {"abcd": "base"})

    docker_ssh.destroy.callback(server="lab", app="app1")

    assert list(build_cache.records) == ["base", "other", "abcd"]


@pytest.fixture
def failed_deploy(build_cache, server):
    """The folder of a first deploy that failed after its build."""
    build_cache.build("myapp", {"deps": "base"})
    app_dir = server / "dallinger/myapp"
    (app_dir / "docker-compose.yml").unlink()
    (app_dir / "logs.jsonl").touch()
    (app_dir / "secrets").mkdir()
    return app_dir


def test_destroy_removes_the_folder_a_failed_deploy_left(
    build_cache, failed_deploy, capsys
):
    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert list(build_cache.records) == ["base", "other"]
    assert not failed_deploy.exists()
    assert "left by a failed deploy" in capsys.readouterr().out


@pytest.mark.parametrize("extra", [".env", "secrets/notes"])
def test_destroy_leaves_a_failed_deploys_folder_with_other_files(
    build_cache, failed_deploy, capsys, extra
):
    (failed_deploy / extra).write_text("KEY=1\n")

    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert list(build_cache.records) == ["base", "other"]
    assert (failed_deploy / extra).exists()
    assert "Left ~/dallinger/myapp on the server" in capsys.readouterr().out


def test_destroy_keeps_a_folder_a_retry_deploys_during_the_prune(
    build_cache, failed_deploy, server
):
    prune = build_cache.prune_builds

    def prune_while_retrying(filters):
        (failed_deploy / "docker-compose.yml").write_text("services: {}\n")
        return prune(filters)

    build_cache.prune_builds = prune_while_retrying

    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert (failed_deploy / "docker-compose.yml").exists()
    assert (failed_deploy / "build-cache-ids").exists()
    log = server / "docker.log"
    assert "down" not in (log.read_text() if log.exists() else "")


def test_destroy_warns_when_it_cant_save_the_leftovers(build_cache, server, capsys):
    build_cache.build("myapp", {"deps": "base"})
    build_cache.shared = {"deps"}
    (server / "dallinger/build-cache-leftovers").mkdir()

    docker_ssh.destroy.callback(server="lab", app="myapp")

    out = capsys.readouterr().out
    assert "could not write ~/dallinger/build-cache-leftovers" in out
    assert "App myapp removed." in out
    assert not list((server / "dallinger/build-cache-leftovers").iterdir())


def test_destroy_keeps_a_failed_deploys_record_when_it_cant_save_the_leftovers(
    build_cache, failed_deploy, server, capsys
):
    build_cache.shared = {"deps"}
    (server / "dallinger/build-cache-leftovers").mkdir()

    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert (failed_deploy / "build-cache-ids").read_text() == "deps\n"
    assert "so that destroying myapp again retries" in capsys.readouterr().out


def test_destroy_tears_down_the_tunnel_of_a_deploy_that_saved_only_its_id(
    server, monkeypatch
):
    secrets = server / "dallinger/myapp/secrets"
    secrets.mkdir(parents=True)
    (secrets / "cloudflare-tunnel-id").write_text("t-1\n")
    cloudflare = mock.Mock(return_value=True)
    monkeypatch.setattr(docker_ssh, "_destroy_cloudflare_resources", cloudflare)

    docker_ssh.destroy.callback(server="lab", app="myapp")

    assert cloudflare.call_args.args == ("myapp", None, "t-1")
    assert not (server / "dallinger/myapp").exists()


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
    monkeypatch.setattr(docker_ssh, "_config_contact_email", lambda *a: (None, None))
    with (
        mock.patch.object(docker_ssh, "prepare_server"),
        mock.patch.object(docker_ssh, "store_host"),
    ):
        result = CliRunner().invoke(docker_ssh.servers, ["add", "--host", "1.2.3.4"])

    assert result.exit_code == 0, result.output
    assert "left unchanged" in result.output


def test_servers_add_ignores_config_keys_dallinger_does_not_register(
    server, monkeypatch
):
    (server / "key.pem").write_text("")
    (server / ".dallingerconfig").write_text(
        "[Parameters]\nlucid_api_key = secret\ncontact_email_on_error = me@example.org\n"
        f"server_pem = {server / 'key.pem'}\n"
    )
    monkeypatch.setenv("HOME", str(server))
    monkeypatch.delenv("contact_email_on_error", raising=False)
    monkeypatch.chdir(server)
    monkeypatch.setattr("dallinger.config.config", None)
    saved = {key: value for key, value in SERVER.items() if key != "contact_email"}
    monkeypatch.setattr(
        docker_ssh, "get_configured_hosts", lambda: {"lab.example.org": saved}
    )
    # Connecting to the server reads server_pem first.
    connect = mock.Mock(side_effect=lambda host, user: docker_ssh.get_server_pem_path())
    with (
        mock.patch.object(docker_ssh, "prepare_server", connect),
        mock.patch.object(docker_ssh, "store_host"),
    ):
        result = CliRunner().invoke(
            docker_ssh.servers, ["add", "--host", "lab.example.org"]
        )

    assert result.exit_code == 0, result.output
    assert "me@example.org (from ~/.dallingerconfig)" in result.output


def test_a_root_route_occupies_the_app_name(server):
    (server / "dallinger/root.d").mkdir()
    (server / "dallinger/root.d/myapp").write_text("reverse_proxy myapp_web:5000\n")

    with pytest.raises(click.Abort):
        docker_ssh._check_app_slot(LocalExecutor(server), "myapp", False, "classic")


def test_servers_add_needs_a_dns_host_to_set_up_a_fresh_ip_server(server, monkeypatch):
    (server / "dallinger/docker-compose.yml").unlink()
    monkeypatch.setattr(docker_ssh, "get_configured_hosts", lambda: {})
    monkeypatch.setattr(docker_ssh, "_config_contact_email", lambda *a: (None, None))
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
    monkeypatch.setattr(
        docker_ssh,
        "_config_contact_email",
        lambda *a: ("me@example.org", "~/.dallingerconfig"),
    )
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
        aws_host, "ubuntu", "1.2.3.4", None, dns_host=dns_host, instance_id="i-1"
    )

    # A new DNS record may still resolve to an older server.
    assert set(ssh_hosts) == {aws_host}
    record = {
        "host": aws_host,
        "user": "ubuntu",
        "default_ingress": "classic",
        "dns_host": dns_host or "1.2.3.4.nip.io",
        "contact_email": "me@example.org",
        "ec2_instance_id": "i-1",
    }
    expected = [record] + ([{**record, "host": dns_host}] if dns_host else [])
    assert {r["host"]: r for r in stored} == {r["host"]: r for r in expected}
    site = dns_host or "1.2.3.4.nip.io"
    assert f"logs.{site} {{" in (server / "dallinger/Caddyfile").read_text()
    for name in SERVER_FILES:
        assert (server / "dallinger" / name).stat().st_mode & 0o777 == 0o444
    assert capsys.readouterr().out.count("password = ") == 1
    assert "up -d" in docker_calls(server)


# Released Dallinger 12.4's Caddyfile after a deploy without --app.
RELEASED_ROOT_CADDYFILE = """
# This is a configuration file for the Caddy http Server
{
    grace_period 30s
}


lab.example.org {
    tls lab@example.org
    handle /health-check {
        respond 200
    }
    handle /logs* {
        reverse_proxy dozzle:8080
    }
    handle {
        reverse_proxy dlgr-abcd1234_web:5000
    }
}
"""
SITE = "caddy.d/dlgr-abcd1234"
APP_SITE = "exp.example.org {\n    tls lab@example.org\n    reverse_proxy x\n}"
MANIFEST = docker_ssh.DeploymentManifest(
    app="dlgr-abcd1234", server="lab", public_origin="https://manifest.example.org"
)


@pytest.mark.parametrize(
    "caddyfile, files, origin",
    [
        (RELEASED_ROOT_CADDYFILE, {}, "https://lab.example.org"),
        # The old root Caddyfile doesn't import caddy.d, so a leftover site isn't served.
        (RELEASED_ROOT_CADDYFILE, {SITE: APP_SITE}, "https://lab.example.org"),
        (
            docker_ssh.CADDYFILE_SERVER.format(host="lab.example.org", tls="tls x"),
            {"root.d/dlgr-abcd1234": "reverse_proxy dlgr-abcd1234_web:5000\n"},
            "https://lab.example.org",
        ),
        (OLD_CADDYFILE, {SITE: APP_SITE}, "https://exp.example.org"),
        (
            docker_ssh.CADDYFILE_SERVER.format(host="lab.example.org", tls="tls x"),
            {SITE: APP_SITE},
            "https://exp.example.org",
        ),
        # Caddy serves no caddy.d site without a Caddyfile that imports caddy.d.
        (
            RELEASED_ROOT_CADDYFILE.replace("dlgr-abcd1234_web", "other_web"),
            {SITE: APP_SITE},
            None,
        ),
        (None, {SITE: APP_SITE}, None),
        (
            OLD_CADDYFILE,
            {SITE: APP_SITE, "dlgr-abcd1234/deployment.json": MANIFEST.to_json()},
            "https://manifest.example.org",
        ),
        (OLD_CADDYFILE, {}, None),
        (
            RELEASED_ROOT_CADDYFILE.replace(
                "reverse_proxy dlgr", "# reverse_proxy dlgr"
            ),
            {SITE: APP_SITE},
            None,
        ),
    ],
    ids=[
        "released-root",
        "leftover-site",
        "root.d",
        "caddy.d",
        "current-caddy.d",
        "released-root-other-app",
        "no-caddyfile",
        "manifest",
        "none",
        "commented-root-route",
    ],
)
def test_get_apps_finds_the_address_of_apps_without_a_manifest(
    server, caddyfile, files, origin
):
    (server / "dallinger/Caddyfile").unlink()
    files = {"Caddyfile": caddyfile, "dlgr-abcd1234/docker-compose.yml": "", **files}
    for name, text in files.items():
        if text is None:
            continue
        path = server / "dallinger" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)

    [app] = docker_ssh.get_apps("lab")

    assert (app.name, app.ingress, app.public_origin) == (
        "dlgr-abcd1234",
        "classic",
        origin,
    )
    on_server_host = docker_ssh._served_at_server_host(
        docker_ssh._executor_for_server("lab"), "dlgr-abcd1234"
    )
    assert on_server_host == (origin == "https://lab.example.org")


def test_existing_app_commands_accept_generated_names(server, monkeypatch):
    app_dir = server / "dallinger/dlgr-abcd1234"
    app_dir.mkdir()
    (app_dir / "docker-compose.yml").write_text("services: {}\n")
    export_db_uri = mock.Mock()
    monkeypatch.setattr(docker_ssh, "export_db_uri", export_db_uri)
    monkeypatch.setattr(docker_ssh, "awaken_app", mock.Mock())
    hibernation = mock.Mock()
    monkeypatch.setattr(docker_ssh, "_run_hibernation_action", hibernation)
    monkeypatch.setattr(
        docker_ssh, "remote_postgres", lambda *a: contextlib.nullcontext("db")
    )

    args = ["--app", "dlgr-abcd1234", "--server", "lab"]
    result = CliRunner().invoke(docker_ssh.export, args + ["--local"])
    assert result.exit_code == 0, result.output
    assert export_db_uri.call_args.args == ("dlgr-abcd1234",)

    result = CliRunner().invoke(docker_ssh.hibernate, args)
    assert result.exit_code == 0, result.output
    assert hibernation.call_args.args[1:] == ("dlgr-abcd1234", "hibernate")
    result = CliRunner().invoke(docker_ssh.awaken, args)
    assert result.exit_code == 0, result.output
    assert docker_ssh.awaken_app.call_args.args[1] == "dlgr-abcd1234"

    result = CliRunner().invoke(docker_ssh.destroy, args)
    assert result.exit_code == 0, result.output
    assert not app_dir.exists()


def test_app_on_the_servers_host_is_updated_there_and_not_redeployed(server, capsys):
    (server / "dallinger/Caddyfile").write_text(RELEASED_ROOT_CADDYFILE)
    (server / "dallinger/dlgr-abcd1234").mkdir()
    (server / "dallinger/dlgr-abcd1234/docker-compose.yml").write_text("")

    with mock.patch.object(docker_ssh, "_check_experiment_hostname_dns") as dns:
        # Released Dallinger's layout needs `servers upgrade` first.
        with pytest.raises(click.Abort):
            docker_ssh._classic_preflight("lab", "dlgr-abcd1234", None, None, False)
        assert "servers upgrade --host lab" in capsys.readouterr().out
        assert dns.call_args.args[1] == "lab.example.org"

        CliRunner().invoke(docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"])
        assert (server / "dallinger/root.d/dlgr-abcd1234").exists()
        # A leftover route without an app is left to the app-name check.
        (server / "dallinger/root.d/dlgr-0000ffff").write_text("reverse_proxy x\n")
        for app, dns_host, update, hostname in [
            ("dlgr-abcd1234", None, True, "lab.example.org"),
            ("dlgr-abcd1234", "other.example.org", True, "lab.example.org"),
            ("dlgr-0000ffff", None, False, "dlgr-0000ffff.lab.example.org"),
            ("dlgr-deadbeef", None, False, "dlgr-deadbeef.lab.example.org"),
        ]:
            preflight = docker_ssh._classic_preflight
            assert preflight("lab", app, None, dns_host, False, update) == hostname
            assert dns.call_args.args[1] == hostname
            ignored = "Ignoring --dns-host other.example.org: dlgr-abcd1234 keeps"
            assert (ignored in capsys.readouterr().out) == bool(dns_host)

        with pytest.raises(click.BadParameter, match="--update --app dlgr-abcd1234"):
            preflight("lab", "dlgr-abcd1234", None, None, False, False)


def test_invalid_env_json_only_warns(capsys):
    executor = mock.Mock(run=mock.Mock(return_value="not json"))

    assert docker_ssh.get_dotenv_values(executor) == {}
    assert ".env.json on the server is not valid JSON" in capsys.readouterr().out
