"""``servers upgrade`` copying the shared PostgreSQL 12 database into the new version."""

import importlib
import json
import subprocess
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
      *) [ ! -f "$HOME/stopped_$app" ] || mv "$HOME/stopped_$app" "$HOME/running_$app";;
    esac 2>/dev/null;;
  "info -f {{.DockerRootDir}}") echo "$HOME";;
  *pg_database_size*) cat "$HOME/db_size" 2>/dev/null || echo 0;;
  *rolpassword*) cat "$HOME/no_password" 2>/dev/null;;
  "volume ls -q") [ ! -f "$HOME/docker_fails" ] || exit 1; cat "$HOME/volumes" 2>/dev/null;;
  *"echo unfinished"*)
    # new_pg_version stands for PostgreSQL 18's /v/*/docker/PG_VERSION.
    # copied_marker is the file the copy leaves behind once it is switched to.
    if [ -f "$HOME/copy_marker" ] || [ ! -f "$HOME/new_pg_version" ]; then
      echo unfinished
    elif [ -f "$HOME/copied_marker" ]; then echo copied
    else echo unrelated; fi
    true;;
  *"--entrypoint touch -v"*)
    case "$*" in
      *copied-from-postgres-12*) touch "$HOME/copied_marker";;
      *) touch "$HOME/copy_marker";;
    esac;;
  *"--entrypoint rm -v"*) rm -f "$HOME/copy_marker";;
  "volume rm -f "*) [ ! -f "$HOME/volume_rm_fails" ] || exit 1; rm -f "$HOME/copy_marker";;
  *"--entrypoint mv -v"*) [ ! -f "$HOME/seal_fails" ] || exit 1; rm -f "$HOME/pg_version";;
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
STOPPED_APPS_RECORD = "dallinger/postgres-upgrade-stopped-apps.json"
UPGRADE = ["upgrade", "--host", "lab", "--yes"]


@pytest.mark.parametrize(
    "volumes, files, expected",
    [
        ([OLD_PG_VOLUME], {"pg_version": "12"}, (12, False)),
        (
            [OLD_PG_VOLUME, NEW_PG_VOLUME],
            {"pg_version": "12", "new_pg_version": "18", "copied_marker": ""},
            (12, True),
        ),
        ([], {}, None),
        ([OLD_PG_VOLUME], {"pg_version": "18"}, None),
        ([OLD_PG_VOLUME, NEW_PG_VOLUME], {}, None),
        ([OLD_PG_VOLUME, NEW_PG_VOLUME], {"pg_version": "12"}, "unfinished copy"),
        (
            [OLD_PG_VOLUME, NEW_PG_VOLUME],
            {"pg_version": "12", "new_pg_version": "18", "copy_marker": ""},
            "unfinished copy",
        ),
        (
            [OLD_PG_VOLUME, NEW_PG_VOLUME],
            {"pg_version": "12", "new_pg_version": "18"},
            "isn't marked as a finished copy",
        ),
        ([OLD_PG_VOLUME], {"pg_version": "12\n18"}, "ambiguous"),
        ([OLD_PG_VOLUME], {"docker_fails": ""}, "remote server"),
    ],
    ids=[
        "postgres-12",
        "copied-not-sealed",
        "fresh-server",
        "postgres-18",
        "empty-old-volume",
        "empty-new-volume",
        "unfinished-copy",
        "not-our-copy",
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


@pytest.mark.parametrize(
    "files, expected",
    [
        ([], "unfinished"),
        ([".dallinger-copy-in-progress", "18/docker/PG_VERSION"], "unfinished"),
        (
            [
                ".dallinger-copy-in-progress",
                ".dallinger-copied-from-postgres-12",
                "18/docker/PG_VERSION",
            ],
            "unfinished",
        ),
        ([".dallinger-copied-from-postgres-12"], "unfinished"),
        ([".dallinger-copied-from-postgres-12", "18/docker/PG_VERSION"], "copied"),
        ([".dallinger-copied-from-postgres-12", "PG_VERSION"], "unfinished"),
        (["18/docker/PG_VERSION"], "unrelated"),
    ],
    ids=[
        "empty",
        "in-progress",
        "both-markers",
        "marker-without-data",
        "copied",
        "marker-with-old-layout",
        "unrelated",
    ],
)
def test_the_new_volume_check_reads_the_markers_and_postgres_18_data(
    tmp_path, files, expected
):
    for name in files:
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_text("18")
    script = pg_upgrade._new_volume_state_script().replace("/v/", f"{tmp_path}/")

    result = subprocess.run(["sh", "-c", script], capture_output=True, text=True)

    assert result.stdout.strip() == expected


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
    assert f"the old volume {OLD_PG_VOLUME} keeps its data" in result.output
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
        # Stops a dump left running by a run that lost its connection.
        "rm -f dallinger_postgres_upgrade_dump",
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
        "/v/.dallinger-copied-from-postgres-12",
        f"--entrypoint rm -v {NEW_PG_VOLUME}:/v",
        f"--entrypoint mv -v {OLD_PG_VOLUME}:/v {POSTGRES_IMAGE} "
        "/v/PG_VERSION /v/PG_VERSION.copied-to-postgres-18",
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
    assert not (server / STOPPED_APPS_RECORD).exists()
    compose = (server / "dallinger/docker-compose.yml").read_text()
    assert "dallinger_pg18_data:/var/lib/postgresql\n" in compose


def _assert_back_on_postgres_12(server, output):
    calls = docker_calls(server)
    assert calls.rindex("start postgresql") > calls.index(
        f"volume rm -f {NEW_PG_VOLUME}"
    )
    assert "myapp/docker-compose.yml start" in calls
    assert "up -d" not in calls
    assert "--entrypoint mv" not in calls
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


def test_an_old_volume_that_could_not_be_sealed_is_sealed_by_the_next_upgrade(
    postgres_12_server,
):
    server = postgres_12_server
    (server / "seal_fails").write_text("")
    upgrade = ["upgrade", "--host", "lab", "--yes"]

    result = CliRunner().invoke(docker_ssh.servers, upgrade)

    assert result.exit_code == 0, result.output
    assert f"could not seal the old volume {OLD_PG_VOLUME}" in result.output
    assert "up -d --wait postgresql" in docker_calls(server)
    assert (server / "copied_marker").is_file()

    (server / "seal_fails").unlink()
    (server / "volumes").write_text(f"{OLD_PG_VOLUME}\n{NEW_PG_VOLUME}\n")
    (server / "new_pg_version").write_text("18")
    result = CliRunner().invoke(docker_ssh.servers, upgrade)
    assert result.exit_code == 0, result.output
    assert "was already copied" in result.output
    assert "stays on the old volume" in result.output
    assert docker_calls(server).count("pg_dumpall") == 1
    assert not (server / "pg_version").exists()


def _leave_a_finished_copy_unsealed(server):
    """The new volume holds a finished copy, and the old one still has its PG_VERSION."""
    (server / "volumes").write_text(f"{OLD_PG_VOLUME}\n{NEW_PG_VOLUME}\n")
    (server / "new_pg_version").write_text("18")
    (server / "copied_marker").write_text("")


def test_an_old_compose_file_is_replaced_and_sealed_without_copying(postgres_12_server):
    server = postgres_12_server
    _leave_a_finished_copy_unsealed(server)
    (server / "dallinger/docker-compose.yml").write_text(
        "image: postgres:12\n    - dallinger_pg_data:/var/lib/postgresql/data\n"
    )
    upgrade = ["upgrade", "--host", "lab", "--yes"]

    result = CliRunner().invoke(docker_ssh.servers, upgrade)

    assert result.exit_code == 0, result.output
    assert "was already copied" in result.output
    assert "stays on the old volume" in result.output
    assert f"Sealed the old volume {OLD_PG_VOLUME}." in result.output
    assert f"docker volume rm {OLD_PG_VOLUME}" in result.output
    calls = docker_calls(server)
    assert "pg_dumpall" not in calls
    assert "docker-compose.yml stop" not in calls
    assert calls.index("--entrypoint mv") < calls.index("up -d --wait postgresql")
    compose = (server / "dallinger/docker-compose.yml").read_text()
    assert "dallinger_pg18_data:/var/lib/postgresql\n" in compose
    assert "postgres:12" not in compose
    assert not (server / "pg_version").exists()

    sealed = calls.count("--entrypoint mv")
    result = CliRunner().invoke(docker_ssh.servers, upgrade)
    assert result.exit_code == 0, result.output
    assert docker_calls(server).count("--entrypoint mv") == sealed
    assert "pg_dumpall" not in docker_calls(server)


def test_a_sealed_server_with_an_older_compose_file_is_restored_without_copying(
    postgres_12_server,
):
    server = postgres_12_server
    _leave_a_finished_copy_unsealed(server)
    (server / "pg_version").unlink()  # sealed: no PG_VERSION
    (server / "dallinger/docker-compose.yml").write_text(
        "image: postgres:12\n    - dallinger_pg_data:/var/lib/postgresql/data\n"
    )

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 0, result.output
    calls = docker_calls(server)
    assert "pg_dumpall" not in calls and "--entrypoint mv" not in calls
    assert "up -d --wait postgresql" in calls
    compose = (server / "dallinger/docker-compose.yml").read_text()
    assert "dallinger_pg18_data:/var/lib/postgresql\n" in compose


def test_a_postgres_18_volume_from_elsewhere_is_not_sealed(postgres_12_server):
    server = postgres_12_server
    (server / "volumes").write_text(f"{OLD_PG_VOLUME}\n{NEW_PG_VOLUME}\n")
    (server / "new_pg_version").write_text("18")

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 1
    message = result.output + str(result.exception)
    assert "isn't marked as a finished copy" in message
    # It can't tell which volume the apps need, so it offers both ways out.
    assert f"docker ps -a --filter volume={NEW_PG_VOLUME}" in message
    assert f"docker volume rm {OLD_PG_VOLUME}" in message
    assert pg_upgrade._seal_command() in message
    # Docker refuses to remove a volume that a container still uses.
    assert "remove those containers" in message
    assert f"docker volume rm {NEW_PG_VOLUME}" in message
    assert "--entrypoint mv" not in docker_calls(server)
    assert (server / "pg_version").read_text() == "12"


def test_a_new_volume_that_cannot_be_read_is_refused_without_advice(
    server, monkeypatch
):
    (server / "volumes").write_text(f"{OLD_PG_VOLUME}\n{NEW_PG_VOLUME}\n")
    (server / "pg_version").write_text("12")
    # The fake Docker prints nothing for a script it doesn't know.
    monkeypatch.setattr(pg_upgrade, "_new_volume_state_script", lambda: "true")

    with pytest.raises(click.ClickException) as e:
        pg_upgrade._shared_postgres_to_migrate(LocalExecutor(server))

    assert "Could not tell" in str(e.value)
    assert "docker volume rm" not in str(e.value)


def test_a_seal_only_run_whose_rename_fails_only_warns(postgres_12_server):
    server = postgres_12_server
    _leave_a_finished_copy_unsealed(server)
    (server / "seal_fails").write_text("")

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab", "--yes"]
    )

    assert result.exit_code == 0, result.output
    assert f"could not seal the old volume {OLD_PG_VOLUME}" in result.output
    assert "Sealed the old volume" not in result.output
    assert (server / "pg_version").read_text() == "12"


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


def _cut_off_at_the_dump(server, monkeypatch):
    """Run an upgrade whose connection drops at the dump, leaving its apps stopped."""
    executor = docker_ssh.Executor()
    run_with_status = executor.run_with_status
    cut = []

    def cut_off_at_the_dump(cmd):
        if cut or "pg_dumpall" in cmd:
            cut.append(cmd)
            raise ConnectionResetError("connection lost")
        return run_with_status(cmd)

    monkeypatch.setattr(executor, "run_with_status", cut_off_at_the_dump)
    result = CliRunner().invoke(docker_ssh.servers, UPGRADE)
    assert isinstance(result.exception, ConnectionResetError)
    assert (server / "stopped_myapp").exists() and (server / "stopped_sleepy").exists()
    monkeypatch.setattr(executor, "run_with_status", run_with_status)
    (server / "docker.log").unlink()


def test_apps_stopped_by_a_cut_off_upgrade_are_started_by_the_next(
    postgres_12_server, monkeypatch
):
    server = postgres_12_server
    _cut_off_at_the_dump(server, monkeypatch)

    result = CliRunner().invoke(docker_ssh.servers, UPGRADE)

    assert result.exit_code == 0, result.output
    assert "stopped, are started again afterwards: myapp, sleepy." in result.output
    assert "an interrupted `servers upgrade` stopped: myapp, sleepy." in result.output
    calls = docker_calls(server)
    assert "myapp/docker-compose.yml stop" not in calls
    assert calls.index("myapp/docker-compose.yml start web worker_1") > calls.index(
        "up -d --wait postgresql"
    )
    assert "sleepy/docker-compose.yml start frontdoor" in calls
    assert not (server / STOPPED_APPS_RECORD).exists()


def test_services_started_by_hand_after_a_cut_off_keep_the_rest_recorded(
    postgres_12_server, monkeypatch
):
    server = postgres_12_server
    _cut_off_at_the_dump(server, monkeypatch)
    (server / "stopped_myapp").rename(server / "running_myapp")
    (server / "running_myapp").write_text("web\n")

    _cut_off_at_the_dump(server, monkeypatch)
    record = json.loads((server / STOPPED_APPS_RECORD).read_text())
    assert record == {"myapp": ["web", "worker_1"], "sleepy": ["frontdoor"]}

    result = CliRunner().invoke(docker_ssh.servers, UPGRADE)
    assert result.exit_code == 0, result.output
    assert "myapp/docker-compose.yml start web worker_1" in docker_calls(server)


@pytest.mark.parametrize(
    "prepare, exit_code",
    [
        (lambda server: (server / "pg_version").unlink(), 0),
        (lambda server: (server / "db_size").write_text(str(2**60)), 1),
    ],
    ids=["nothing-to-copy", "copy-refused"],
)
def test_recorded_apps_are_started_whether_or_not_the_copy_is_made(
    postgres_12_server, prepare, exit_code
):
    server = postgres_12_server
    (server / "running_myapp").rename(server / "stopped_myapp")
    (server / STOPPED_APPS_RECORD).write_text('{"myapp": ["web", "worker_1"]}')
    prepare(server)

    result = CliRunner().invoke(
        docker_ssh.servers, ["upgrade", "--host", "lab"], input="y\n"
    )

    assert result.exit_code == exit_code, result.output
    before_asking = result.output.split("Continue?")[0]
    assert "stopped, are started again afterwards: myapp." in before_asking
    assert (server / "running_myapp").exists()
    assert not (server / STOPPED_APPS_RECORD).exists()


def test_an_unreadable_record_of_stopped_apps_only_warns(postgres_12_server):
    server = postgres_12_server
    (server / STOPPED_APPS_RECORD).write_text("not json")

    result = CliRunner().invoke(docker_ssh.servers, UPGRADE)

    assert result.exit_code == 0, result.output
    assert f"Warning: ignoring ~/{STOPPED_APPS_RECORD}" in result.output
    assert not (server / STOPPED_APPS_RECORD).exists()
