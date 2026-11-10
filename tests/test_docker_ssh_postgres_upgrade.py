"""``servers upgrade`` copying the shared PostgreSQL 12 database into the new version."""

import importlib
from unittest import mock

import click
import pytest
from click.testing import CliRunner

from dallinger.docker.postgres import POSTGRES_IMAGE
from tests.test_docker_ssh_server_files import (
    LocalExecutor,
    LocalSftp,
    docker_calls,
    set_up_server,
)

docker_ssh = importlib.import_module("dallinger.command_line.docker_ssh")
pg_upgrade = importlib.import_module(
    "dallinger.command_line.docker_ssh_postgres_upgrade"
)

# What the copy asks Docker, answered from files in the fake server's home.
COPY_DOCKER_CASES = """\
  *"/docker-compose.yml ps --services --status running --status restarting")
    [ ! -f "$HOME/compose_ps_fails" ] || exit 1
    args="$*"; app=${args#*/dallinger/}; cat "$HOME/running_${app%%/*}" 2>/dev/null;;
  *"/docker-compose.yml stop"|*"/docker-compose.yml start "*)
    args="$*"; app=${args#*/dallinger/}; app=${app%%/*}
    case "$args" in
      *" stop")
        [ "$app" != myapp ] || [ ! -f "$HOME/stop_fails" ] || exit 1
        [ -f "$HOME/stays_running" ] || mv "$HOME/running_$app" "$HOME/stopped_$app";;
      *) mv "$HOME/stopped_$app" "$HOME/running_$app";;
    esac 2>/dev/null;;
  "info -f {{.DockerRootDir}}") echo "$HOME";;
  *pg_database_size*) cat "$HOME/db_size" 2>/dev/null || echo 0;;
  *rolpassword*) cat "$HOME/no_password" 2>/dev/null;;
  "volume ls -q") [ ! -f "$HOME/docker_fails" ] || exit 1; cat "$HOME/volumes" 2>/dev/null;;
  *"echo unfinished"*)
    cat "$HOME/copy_unfinished" 2>/dev/null || [ ! -f "$HOME/copy_marker" ] || echo unfinished;;
  *"--entrypoint touch -v"*) touch "$HOME/copy_marker";;
  *"--entrypoint rm -v"*) rm -f "$HOME/copy_marker";;
  "volume rm -f "*) [ ! -f "$HOME/volume_rm_fails" ] || exit 1; rm -f "$HOME/copy_marker";;
  *PG_VERSION*) cat "$HOME/pg_version" 2>/dev/null;;
  *pg_roles*) cat "$HOME/roles" 2>/dev/null;;
  *"psql -U dallinger -d postgres -q -o /dev/null") cat "$HOME/restore_output" 2>/dev/null;;
"""


@pytest.fixture
def server(tmp_path, monkeypatch):
    """A fake server home whose ``docker`` also answers the copy's commands."""
    return set_up_server(tmp_path, monkeypatch, COPY_DOCKER_CASES)


OLD_PG_VOLUME = "dallinger_dallinger_pg_data"
NEW_PG_VOLUME = "dallinger_dallinger_pg18_data"


@pytest.mark.parametrize(
    "volumes, files, expected",
    [
        ([OLD_PG_VOLUME], {"pg_version": "12"}, 12),
        ([OLD_PG_VOLUME, NEW_PG_VOLUME], {"pg_version": "12"}, None),
        ([], {}, None),
        ([OLD_PG_VOLUME], {"pg_version": "18"}, None),
        ([OLD_PG_VOLUME, NEW_PG_VOLUME], {}, None),
        (
            [OLD_PG_VOLUME, NEW_PG_VOLUME],
            {"pg_version": "12", "copy_unfinished": "unfinished"},
            "unfinished copy",
        ),
        ([OLD_PG_VOLUME], {"pg_version": "12\n18"}, "ambiguous"),
        ([OLD_PG_VOLUME], {"docker_fails": ""}, "remote server"),
    ],
    ids=[
        "postgres-12",
        "copied",
        "fresh-server",
        "postgres-18",
        "empty-old-volume",
        "unfinished-copy",
        "two-versions",
        "docker-fails",
    ],
)
def test_servers_upgrade_copies_only_an_old_shared_database(
    server, volumes, files, expected
):
    (server / "volumes").write_text("\n".join(volumes))
    for name, content in files.items():
        (server / name).write_text(content)
    executor = LocalExecutor(server)
    if isinstance(expected, str):
        with pytest.raises((click.ClickException, docker_ssh.ExecuteException)) as e:
            pg_upgrade._shared_postgres_to_migrate(executor)
        assert expected in str(e.value)
    else:
        assert pg_upgrade._shared_postgres_to_migrate(executor) == expected


@pytest.fixture
def postgres_12_server(server, monkeypatch):
    """The server, with its shared database on PostgreSQL 12 and its apps.

    ``myapp`` runs, ``sleepy`` hibernates and ``oldapp``, deployed by
    Dallinger 12 and stopped, keeps its password in its compose file.
    """
    # The real df measures this machine's disk; only db_size decides the fit.
    monkeypatch.setattr(pg_upgrade, "_COPY_SPARE_BYTES", 0)
    (server / "volumes").write_text(OLD_PG_VOLUME)
    (server / "pg_version").write_text("12")
    (server / "roles").write_text("dallinger\nmyapp\noldapp\n")
    for app, running in (("myapp", "web\nworker_1\n"), ("sleepy", "frontdoor\n")):
        (server / "dallinger" / app).mkdir()
        (server / "dallinger" / app / "docker-compose.yml").write_text("")
        (server / f"running_{app}").write_text(running)
    (server / "dallinger/myapp/.env").write_text("POSTGRES_PASSWORD=s3cret\n")
    (server / "dallinger/oldapp").mkdir()
    (server / "dallinger/oldapp/docker-compose.yml").write_text(
        "      - POSTGRESQL_PASSWORD=0ldpw\n"
    )
    apps = [
        docker_ssh.App("myapp", "running", "classic"),
        docker_ssh.App("oldapp", "inactive", "classic"),
        docker_ssh.App("sleepy", "hibernating", "classic"),
        docker_ssh.App("tunnelled", "running", "cloudflare"),
        docker_ssh.App("idle", "inactive", "classic"),
    ]
    monkeypatch.setattr(pg_upgrade, "get_apps", lambda server: apps)
    return server


def test_servers_upgrade_copies_the_shared_database_into_postgres_18(
    postgres_12_server, monkeypatch
):
    server = postgres_12_server
    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab"], input="n\n"
    )
    assert result.exit_code == 1
    assert f"the old volume {OLD_PG_VOLUME} is kept unchanged" in result.output
    assert "started again afterwards: myapp, sleepy." in result.output
    assert "pg_dumpall" not in docker_calls(server)

    # A role named like a directory that holds no app only gets a warning.
    (server / "dallinger/root.d").mkdir()
    (server / "roles").write_text("dallinger\nmyapp\noldapp\nroot.d\n")
    (server / "no_password").write_text("root.d\n")
    (server / "restore_output").write_text(
        'ERROR:  role "dallinger" already exists\nWARNING:  something to know\n'
    )
    commands = []
    executor = docker_ssh.Executor()
    run_with_status = executor.run_with_status
    monkeypatch.setattr(
        executor,
        "run_with_status",
        lambda cmd: commands.append(cmd) or run_with_status(cmd),
    )
    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 0, result.output
    calls = docker_calls(server)
    steps = [
        "start postgresql",
        "myapp/docker-compose.yml stop",
        "sleepy/docker-compose.yml stop",
        # The new version's client, which keeps the old privileges on public.
        f"--network container: -e PGPASSWORD=dallinger {POSTGRES_IMAGE} "
        "pg_dumpall -h 127.0.0.1 -U dallinger --no-role-passwords",
        f"volume create --label com.docker.compose.project=dallinger "
        f"--label com.docker.compose.volume=dallinger_pg18_data {NEW_PG_VOLUME}",
        f"--entrypoint touch -v {NEW_PG_VOLUME}:/v",
        "-e pw dallinger_postgres_upgrade psql",
        "-v app=myapp\nenvironment pw=s3cret",
        "-v app=oldapp\nenvironment pw=0ldpw",
        "rm dallinger_postgres_upgrade",
        f"--entrypoint rm -v {NEW_PG_VOLUME}:/v",
        "up -d --wait postgresql",
        "myapp/docker-compose.yml start web worker_1",
        "sleepy/docker-compose.yml start frontdoor\n",
    ]
    assert [calls.index(step) for step in steps] == sorted(
        calls.index(step) for step in steps
    )
    arguments = [line for line in calls.splitlines() if "environment" not in line]
    for password in ("s3cret", "0ldpw"):
        assert not any(password in command for command in commands + arguments)
    assert f"volume rm {OLD_PG_VOLUME}" not in calls
    assert "can't log in over the network until one is set: root.d." in result.output
    assert "restoring the shared databases: WARNING:  something" in result.output
    assert f"`docker volume rm {OLD_PG_VOLUME}`" in result.output
    assert not (server / "dallinger/postgres-upgrade.sql").exists()
    compose = (server / "dallinger/docker-compose.yml").read_text()
    assert "dallinger_pg18_data:/var/lib/postgresql\n" in compose


def _assert_back_on_postgres_12(server, output):
    calls = docker_calls(server)
    assert calls.rindex("start postgresql") > calls.index(
        f"volume rm -f {NEW_PG_VOLUME}"
    )
    assert "myapp/docker-compose.yml start" in calls
    assert "up -d" not in calls
    assert not (server / "dallinger/postgres-upgrade.sql").exists()
    assert "Copied the shared databases" not in output


@pytest.mark.parametrize(
    "fault, message",
    [
        ({"restore_output": 'ERROR:  relation "x" already exists\n'}, "already exists"),
        (
            {"restore_output": '\\connect: FATAL:  database "myapp" does not exist\n'},
            "failed: \\connect",
        ),
        ({"stop_fails": ""}, "exit code was not 0"),
        ({"no_password": "myapp\n"}, "password of these apps on the server: myapp."),
        ({"stays_running": ""}, "still run after being stopped: myapp, sleepy."),
    ],
    ids=["restore", "restore-psql", "app-stop", "app-password", "app-still-runs"],
)
def test_a_failed_copy_puts_the_server_back_on_postgres_12(
    postgres_12_server, fault, message
):
    server = postgres_12_server
    for name, content in fault.items():
        (server / name).write_text(content)

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 1
    assert message in result.output + str(result.exception)
    _assert_back_on_postgres_12(server, result.output)
    compose = (server / "dallinger/docker-compose.yml").read_text()
    assert compose == "services: {}  # edited\n"


@pytest.mark.parametrize(
    "fault, message",
    [
        ("compose_ps_fails", "exit code was not 0"),
        ("db_size", "Free some space on the server"),
    ],
    ids=["app-cannot-say-what-runs", "disk-too-small"],
)
def test_no_app_is_stopped_if_the_copy_cannot_start(postgres_12_server, fault, message):
    (postgres_12_server / fault).write_text(str(2**60))

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 1
    assert message in result.output + str(result.exception)
    calls = docker_calls(postgres_12_server)
    assert "docker-compose.yml stop" not in calls
    assert "pg_dumpall" not in calls


@pytest.mark.parametrize("volume_removed", [True, False], ids=["undone", "volume-kept"])
def test_an_upgrade_undone_after_writing_the_compose_file_copies_again(
    postgres_12_server, monkeypatch, volume_removed
):
    server = postgres_12_server
    if not volume_removed:
        (server / "volume_rm_fails").write_text("")

    class FailingSftp(LocalSftp):
        def putfo(self, fo, path):
            if path == "dallinger/Caddyfile":
                raise OSError("connection lost")
            super().putfo(fo, path)

    monkeypatch.setattr(docker_ssh, "get_sftp", lambda *a, **k: FailingSftp(server))
    upgrade = ["upgrade", "--host", "lab", "--yes"]
    result = CliRunner().invoke(docker_ssh.servers, upgrade)

    assert result.exit_code == 1
    assert "rm dallinger_postgres_upgrade" in docker_calls(server)
    _assert_back_on_postgres_12(server, result.output)
    assert "pg18_data" in (server / "dallinger/docker-compose.yml").read_text()

    monkeypatch.setattr(docker_ssh, "get_sftp", lambda *a, **k: LocalSftp(server))
    if not volume_removed:
        # The old database may have changed since, so the copy is refused.
        (server / "volumes").write_text(f"{OLD_PG_VOLUME}\n{NEW_PG_VOLUME}\n")
        result = CliRunner().invoke(docker_ssh.servers, upgrade)
        assert result.exit_code == 1
        assert "an unfinished copy" in result.output + str(result.exception)
        assert "up -d" not in docker_calls(server)
        return
    result = CliRunner().invoke(docker_ssh.servers, upgrade)
    assert result.exit_code == 0, result.output
    assert docker_calls(server).count("pg_dumpall") == 2


def test_a_failure_after_the_switch_keeps_the_copy(postgres_12_server, monkeypatch):
    server = postgres_12_server
    start = docker_ssh._start_server_services
    monkeypatch.setattr(
        docker_ssh,
        "_start_server_services",
        mock.Mock(side_effect=docker_ssh.ExecuteException("postgres did not start")),
    )
    upgrade = ["upgrade", "--host", "lab", "--yes"]
    result = CliRunner().invoke(docker_ssh.servers, upgrade)

    assert result.exit_code == 1
    assert "The copied databases are kept" in result.output
    assert "volume rm -f" not in docker_calls(server)
    assert "myapp/docker-compose.yml start" in docker_calls(server)

    (server / "volumes").write_text(f"{OLD_PG_VOLUME}\n{NEW_PG_VOLUME}\n")
    monkeypatch.setattr(docker_ssh, "_start_server_services", start)
    result = CliRunner().invoke(docker_ssh.servers, upgrade)
    assert result.exit_code == 0, result.output
    assert docker_calls(server).count("pg_dumpall") == 1
    assert "up -d --wait postgresql" in docker_calls(server)
