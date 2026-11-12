"""Copy a docker-ssh server's shared PostgreSQL into a newer major version.

PostgreSQL only opens a data directory in the major version that created it,
so when :data:`dallinger.docker.postgres.POSTGRES_MAJOR` rises, the shared
Postgres of a classic-ingress server needs its databases copied into a new
volume. ``dallinger docker-ssh servers upgrade`` does that through
:func:`planned_copy` and :func:`copied_shared_postgres`; nothing else here is
meant to be called from outside.

The copy stops the server's classic apps, dumps every database and role with
the new version's ``pg_dumpall``, restores them into a temporary container on
the new volume and sets the apps' passwords again. The copy doesn't change
the old volume, and a copy that fails before the shared services switch to it
is undone. After the switch, the old volume is sealed so that PostgreSQL 12
no longer starts on it. If that didn't happen, a later run seals it, but only
when the new volume has the marker the copy left. This module only handles the
PostgreSQL 12 volume of Dallinger 13.0 and earlier, so it can be deleted, with
its tests, once no such server is left.
"""

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from shlex import quote

import click

from dallinger.command_line.docker_ssh import SERVER_COMPOSE, _volume_major, get_apps
from dallinger.command_line.lib.app_manifest import INGRESS_CLASSIC
from dallinger.docker import postgres
from dallinger.utils import END, RED

# Compose prefixes the shared services' volumes with their project name,
# ``dallinger``.
_SERVER_POSTGRES_VOLUME = f"dallinger_dallinger_pg{postgres.POSTGRES_MAJOR}_data"
# The shared PostgreSQL 12 volume that Dallinger 13.0 and earlier set up.
_OLD_SERVER_POSTGRES_VOLUME = "dallinger_dallinger_pg_data"
_POSTGRES_UPGRADE_CONTAINER = "dallinger_postgres_upgrade"
_POSTGRES_UPGRADE_DUMP = "~/dallinger/postgres-upgrade.sql"
# Named so that a dump left running by a run that lost its connection can be
# stopped before it writes into the next run's dump.
_POSTGRES_DUMP_CONTAINER = "dallinger_postgres_upgrade_dump"
# Kept in the new volume until the shared services switch to it, so that a
# copy left by an interrupted run, or by an undo that couldn't remove it, is
# refused: apps may have written to the old database since.
_COPY_IN_PROGRESS_MARKER = ".dallinger-copy-in-progress"
# Left in the new volume once the copy is switched to. After the marker above
# is removed, a database the shared services created itself looks the same as
# a finished copy; this file is how a later run tells them apart.
_COPY_FINISHED_MARKER = ".dallinger-copied-from-postgres-12"
# What PG_VERSION in the old volume is renamed to once the shared services
# switch to the copy. A server compose file that an older Dallinger writes
# back (with a Dallinger 12 deploy, or `servers upgrade` from 13.0) would
# otherwise start PostgreSQL 12 on the data from before the copy, and the
# apps would silently lose what they wrote since. Without PG_VERSION, the
# image's initdb refuses the non-empty directory, so Postgres doesn't start.
# Renaming the file back makes the volume usable again.
_SEALED_PG_VERSION = f"PG_VERSION.copied-to-postgres-{postgres.POSTGRES_MAJOR}"
# Lists the apps that a copy stops, with the services that ran, until they
# are started again. A run cut off in between (by a closed connection, for
# example) can't start them, so the next run does.
_STOPPED_APPS_RECORD = "~/dallinger/postgres-upgrade-stopped-apps.json"
_REMOVE_OLD_VOLUME = (
    "Once the apps work, remove the old volume on the server with "
    f"`docker volume rm {_OLD_SERVER_POSTGRES_VOLUME}`."
)
# A dump restored into a fresh cluster recreates the cluster's own owner and
# database, which initdb already made.
_EXPECTED_RESTORE_ERRORS = (
    'ERROR:  role "dallinger" already exists',
    'ERROR:  database "dallinger" already exists',
)
# Server notices during the restore are reported but don't fail it. Any other
# line does, including psql's own errors, which have no ``ERROR:`` prefix: after
# a refused ``\connect``, the rest of the dump runs in the wrong database.
_RESTORE_NOTICE_PREFIXES = ("NOTICE:", "WARNING:", "DETAIL:", "HINT:", "CONTEXT:")
# Room for the new cluster's WAL and catalogs beyond the dump and the data.
_COPY_SPARE_BYTES = 256 * 2**20
# The password comes from the environment, which, unlike arguments, other
# users can't see in ``ps``. psql quotes the variables it substitutes, so it
# needs no escaping.
_RESET_PASSWORD_SQL = "\\getenv pw pw\nALTER ROLE :\"app\" PASSWORD :'pw';"


def _shared_postgres_to_migrate(executor):
    """Return ``(major, copied)`` for an unsealed older shared database, or None.

    That is an older PostgreSQL's database in the volume that Dallinger 13.0
    and earlier set up. ``copied`` says whether the current version's volume
    holds this command's finished copy (see :data:`_COPY_FINISHED_MARKER`).
    A new volume with no database, or with the marker of an unfinished copy,
    is refused with the commands that remove it, because only the operator
    can tell that nothing uses it. A database without the finished-copy
    marker is refused too, because only the operator can tell which volume
    holds the data the apps need. If the check gives no
    known answer, that is refused without advice.
    """
    volumes = set(executor.run("docker volume ls -q").split())
    if _OLD_SERVER_POSTGRES_VOLUME not in volumes:
        return None
    major = _volume_major(executor, _OLD_SERVER_POSTGRES_VOLUME)
    if major is None or major == postgres.POSTGRES_MAJOR:
        return None
    if _SERVER_POSTGRES_VOLUME not in volumes:
        return major, False
    state = executor.run(
        f"docker run --rm --entrypoint sh -v {_SERVER_POSTGRES_VOLUME}:/v:ro "
        f"{postgres.POSTGRES_IMAGE} -c {quote(_new_volume_state_script())}"
    ).strip()
    if state == "copied":
        return major, True
    if state == "unrelated":
        raise click.ClickException(
            f"The volume {_SERVER_POSTGRES_VOLUME} holds a PostgreSQL "
            f"{postgres.POSTGRES_MAJOR} database that isn't marked as a finished "
            f"copy from {_OLD_SERVER_POSTGRES_VOLUME}, so nothing was changed. "
            "Decide which volume holds the data your apps need; "
            f"`docker ps -a --filter volume={_SERVER_POSTGRES_VOLUME}` lists the "
            "containers that use the new one. If it is the new volume, remove "
            "the old volume with "
            f"`docker volume rm {_OLD_SERVER_POSTGRES_VOLUME}`, or seal it with "
            f"`{_seal_command()}` to keep its data. If it is the old volume, "
            "whose data was never copied, remove those containers (Docker "
            "refuses to remove a volume that one still uses) and then the new "
            f"volume with `docker volume rm {_SERVER_POSTGRES_VOLUME}` instead. "
            "Then run this command again; in the second case it copies the "
            "old data."
        )
    if state != "unfinished":
        raise click.ClickException(
            f"Could not tell what the volume {_SERVER_POSTGRES_VOLUME} holds: "
            f"its check answered {state[:200]!r}, not `copied`, `unfinished` "
            "or `unrelated`. Nothing was changed."
        )
    raise click.ClickException(
        f"The volume {_SERVER_POSTGRES_VOLUME} holds no database or an unfinished "
        "copy of the shared database, left by an interrupted or undone "
        "`servers upgrade`; "
        f"the old volume {_OLD_SERVER_POSTGRES_VOLUME} is unchanged. Remove the "
        f"copy on the server with `docker rm -f {_POSTGRES_UPGRADE_CONTAINER}; "
        f"docker volume rm {_SERVER_POSTGRES_VOLUME}`, then run this command again. "
        "The apps that the interrupted run stopped are started again once the "
        "copy is done."
    )


def _classic_apps_to_stop(server, executor):
    """Return ``{app: services}``, the running services of each classic-ingress app.

    Each app's Compose is asked, and a failure raises, so that no app that
    can write to the shared database is missed. That includes hibernating
    apps, whose front door a visitor can wake; starting only the services
    that ran keeps them hibernated.
    """
    classic = sorted(
        app.name for app in get_apps(server) if app.ingress == INGRESS_CLASSIC
    )
    apps = {}
    for app in classic:
        if not executor.run(
            f"test -f ~/dallinger/{quote(app)}/docker-compose.yml && echo yes",
            raise_=False,
        ):
            continue
        services = _running_services(executor, app)
        if services:
            apps[app] = services
    return apps


@dataclass(frozen=True)
class SharedPostgresCopy:
    """A copy of the shared database that ``servers upgrade`` is about to make.

    ``major`` is the old cluster's version, or None if there is nothing to
    copy or seal; ``apps`` maps each classic app to stop to its running
    services. If ``copied``, an earlier run made the copy but didn't seal the
    old volume, so only that is left to do. ``left`` maps each app that a
    cut-off run stopped (see :data:`_STOPPED_APPS_RECORD`) to the services
    that are still to be started and that ``apps`` doesn't list.
    """

    major: int | None
    apps: dict
    copied: bool = False
    left: dict = field(default_factory=dict)

    def describe(self):
        """Explain the copy before ``servers upgrade`` asks to continue."""
        if self.copied:
            print(
                f"The shared PostgreSQL {self.major} database in the old volume "
                f"{_OLD_SERVER_POSTGRES_VOLUME} was already copied into "
                f"{_SERVER_POSTGRES_VOLUME}. The old volume keeps its data, but "
                f"its PG_VERSION file is renamed so that PostgreSQL {self.major} "
                "no longer starts on it. Anything written to PostgreSQL "
                f"{self.major} since that copy stays on the old volume."
            )
        elif self.major is not None:
            print(
                f"The shared PostgreSQL moves from version {self.major} to "
                f"{postgres.POSTGRES_MAJOR}. Its databases are copied into the new "
                f"volume {_SERVER_POSTGRES_VOLUME}; the old volume "
                f"{_OLD_SERVER_POSTGRES_VOLUME} keeps its data, but its PG_VERSION "
                f"file is renamed so that PostgreSQL {self.major} no longer starts "
                "on it."
            )
        if self.apps:
            print(
                "These classic apps are stopped during the copy, and the services "
                f"that ran are started again afterwards: {', '.join(self.apps)}."
            )
        if self.left:
            print(
                "These classic apps, which an interrupted `servers upgrade` "
                f"stopped, are started again afterwards: {', '.join(self.left)}."
            )


def planned_copy(server, executor):
    """Return the :class:`SharedPostgresCopy` that ``server`` needs, or None."""
    found = _shared_postgres_to_migrate(executor)
    recorded = _recorded_stopped_apps(executor)
    if found is None:
        return SharedPostgresCopy(None, {}, left=recorded) if recorded else None
    major, copied = found
    apps = {} if copied else _classic_apps_to_stop(server, executor)
    left = {
        app: [service for service in services if service not in apps.get(app, ())]
        for app, services in recorded.items()
    }
    left = {app: services for app, services in left.items() if services}
    return SharedPostgresCopy(major, apps, copied, left)


@contextmanager
def copied_shared_postgres(executor, server, copy):
    """Make ``copy``, if any, then let the caller switch the shared services to it.

    Yields a function that the caller calls right before it starts the shared
    services on the new version; it marks the copy finished and seals the old
    volume (see :func:`_seal_old_volume`). From then on apps may write to the
    copy, so a failure keeps it; a failure before that undoes it. The stopped
    apps are started again either way. A ``copy`` that an earlier run made
    only has the old volume sealed. Apps that a cut-off run stopped (see
    :data:`_STOPPED_APPS_RECORD`) are started again too, even without a copy.
    """
    stopping = copy.apps if copy else {}
    left = copy.left if copy else {}
    if stopping:
        _record_stopped_apps(
            executor,
            {
                app: [*stopping.get(app, []), *left.get(app, [])]
                for app in {**stopping, **left}
            },
        )
    try:
        if copy is None or copy.major is None:
            yield lambda: None
        elif copy.copied:
            yield from _seal_only(executor, server)
        else:
            yield from _copy(executor, server, copy)
    finally:
        if left:
            print(
                "Starting the apps that an interrupted `servers upgrade` stopped: "
                f"{', '.join(left)}."
            )
            _start_apps(executor, left)
        executor.run(f"rm -f {_STOPPED_APPS_RECORD}")


def _seal_only(executor, server):
    """Yield the switch of a ``servers upgrade`` that only has to seal the old volume."""
    sealed = False

    def seal():
        nonlocal sealed
        sealed = _seal_old_volume(executor, server)

    yield seal
    if sealed:
        print(
            f"Sealed the old volume {_OLD_SERVER_POSTGRES_VOLUME}. {_REMOVE_OLD_VOLUME}"
        )


def _copy(executor, server, copy):
    """Make ``copy`` and yield the switch to it (see :func:`copied_shared_postgres`)."""
    stopped = _migrate_shared_postgres(executor, copy.major, copy.apps)
    switched = False

    def switch():
        nonlocal switched
        executor.run(_volume_file_command("touch", _COPY_FINISHED_MARKER))
        executor.run(_volume_file_command("rm", _COPY_IN_PROGRESS_MARKER))
        switched = True
        _seal_old_volume(executor, server)

    try:
        yield switch
    except BaseException:
        if not switched:
            _undo_shared_postgres_copy(executor, copy.major)
        else:
            print(
                f"{RED}The shared services did not start on PostgreSQL "
                f"{postgres.POSTGRES_MAJOR}. The copied databases are kept; run "
                f"`dallinger docker-ssh servers upgrade --host {quote(server)}` "
                f"again to start them.{END}"
            )
        raise
    finally:
        _start_apps(executor, stopped)
    print(
        "Copied the shared databases into PostgreSQL "
        f"{postgres.POSTGRES_MAJOR}. {_REMOVE_OLD_VOLUME}"
    )


def _app_compose(app):
    return f"docker compose -f ~/dallinger/{quote(app)}/docker-compose.yml"


def _record_stopped_apps(executor, apps):
    """Save ``apps`` in :data:`_STOPPED_APPS_RECORD`, before any of them is stopped."""
    executor.run(f"printf '%s\\n' {quote(json.dumps(apps))} > {_STOPPED_APPS_RECORD}")


def _recorded_stopped_apps(executor):
    """Return the apps that :data:`_STOPPED_APPS_RECORD` lists, with their services.

    An unreadable record only warns, because the apps it lists can still be
    started by hand.
    """
    output = executor.run(f"cat {_STOPPED_APPS_RECORD} 2>/dev/null || true")
    if not output.strip():
        return {}
    try:
        apps = {
            str(app): [str(service) for service in services]
            for app, services in json.loads(output).items()
        }
    except (AttributeError, TypeError, ValueError):
        print(
            f"{RED}Warning: ignoring {_STOPPED_APPS_RECORD}, which doesn't list "
            f"apps: {output.strip()[:200]!r}.{END} Start any app that an "
            "interrupted `servers upgrade` stopped with "
            "`docker compose -f ~/dallinger/<app>/docker-compose.yml start`."
        )
        return {}
    return apps


def _start_apps(executor, apps):
    """Start the services of the apps that a copy stopped.

    ``apps`` maps each app to those services. Failures only warn.
    """
    for app, services in apps.items():
        command = f"{_app_compose(app)} start {' '.join(map(quote, services))}"
        status, _, error = executor.run_with_status(command)
        if status != 0:
            print(
                f"{RED}Warning: could not start {app} again: {error.strip()}{END} "
                f"Start it on the server with `{command}`."
            )


def _check_free_space(executor, container_command):
    """Refuse the copy if the server's disks can't hold the dump and the new cluster.

    Each takes about the size of the old databases. The dump goes to
    ``~/dallinger`` and the new volume to Docker's data directory, which are
    often the same file system.
    """
    [size] = _psql_query(
        executor,
        container_command,
        "SELECT coalesce(sum(pg_database_size(datname)), 0) FROM pg_database",
    )
    root = executor.run("docker info -f '{{.DockerRootDir}}'").strip()
    output = executor.run(f"df -Pk ~/dallinger {quote(root)}")
    free, need = {}, {}
    for row in (line.split() for line in output.splitlines()[1:]):
        free[row[0]] = int(row[3]) * 1024
        need[row[0]] = need.get(row[0], _COPY_SPARE_BYTES) + int(size)
    for filesystem, available in free.items():
        if available < need[filesystem]:
            raise click.ClickException(
                f"The copy needs about {need[filesystem] / 2**30:.1f} GiB on "
                f"{filesystem}, which has {available / 2**30:.1f} GiB free (the "
                f"shared databases take {int(size) / 2**30:.1f} GiB). Free some "
                "space on the server, then run this command again."
            )


def _running_services(executor, app):
    """Return the services of ``app`` that run or that Docker is restarting."""
    return executor.run(
        f"{_app_compose(app)} ps --services --status running --status restarting"
    ).split()


def _psql_query(executor, container_command, sql):
    """Run ``sql`` as the cluster owner and return its unaligned rows."""
    output = executor.run(
        f"{container_command} psql -U dallinger -d postgres -tA "
        f"-v ON_ERROR_STOP=1 -c {quote(sql)}"
    )
    return [line for line in output.splitlines() if line]


def _cluster_contents(executor, container_command):
    """Return the databases and roles of a cluster, to compare a copy with it."""
    databases = _psql_query(
        executor,
        container_command,
        "SELECT datname FROM pg_database WHERE datallowconn ORDER BY 1",
    )
    roles = _psql_query(
        executor,
        container_command,
        "SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY 1",
    )
    return databases, roles


def _reset_role_passwords(executor, container, roles):
    """Set the passwords that the dump leaves out, in the Postgres ``container``.

    Each app role gets its app's password, read on the server so that no
    password appears in a command, which an error message would print. Apps
    deployed by Dallinger 13.0 or later keep it as ``POSTGRES_PASSWORD`` in
    their ``.env``, older ones as ``POSTGRESQL_PASSWORD`` in their compose
    file, where newer ones only refer to the ``.env`` value. An app whose
    password isn't found raises, because it couldn't log in afterwards.
    """
    container_command = f"docker exec -i {container}"
    owner = "ALTER ROLE dallinger PASSWORD 'dallinger'"
    options = "psql -U dallinger -d postgres -q -v ON_ERROR_STOP=1"
    executor.run(f"{container_command} {options} -c {quote(owner)}")
    listing = executor.run("ls -1 ~/dallinger/*/docker-compose.yml 2>/dev/null || true")
    apps = {line.rsplit("/", 2)[-2] for line in listing.splitlines() if line.strip()}
    app_roles = sorted(apps & set(roles))
    for app in app_roles:
        directory = f"~/dallinger/{quote(app)}"
        executor.run(
            f"pw=$(grep -m1 '^POSTGRES_PASSWORD=' {directory}/.env 2>/dev/null "
            '| cut -d= -f2-); [ -n "$pw" ] || '
            "pw=$(sed -n 's/^ *- POSTGRESQL_PASSWORD=//p' "
            f"{directory}/docker-compose.yml 2>/dev/null | head -n 1); "
            "case \"$pw\" in ''|*'${'*) ;; *) "
            f"printf '%s\\n' {quote(_RESET_PASSWORD_SQL)} | "
            f'pw="$pw" docker exec -i -e pw {container} {options} '
            f"-v app={quote(app)};; esac"
        )
    without_password = _psql_query(
        executor,
        container_command,
        "SELECT rolname FROM pg_authid WHERE rolcanlogin AND rolpassword IS NULL "
        "AND rolname !~ '^pg_' ORDER BY 1",
    )
    apps_without_password = [role for role in without_password if role in app_roles]
    if apps_without_password:
        raise click.ClickException(
            "Could not find the database password of these apps on the server: "
            f"{', '.join(apps_without_password)}. Neither ~/dallinger/<app>/.env "
            "nor ~/dallinger/<app>/docker-compose.yml has one. Update or destroy "
            "those apps, then run this command again."
        )
    if without_password:
        print(
            f"{RED}Warning: these roles have no password in PostgreSQL "
            f"{postgres.POSTGRES_MAJOR} and can't log in over the network until "
            f"one is set: {', '.join(without_password)}.{END}"
        )


def _restore_shared_postgres(executor, expected):
    """Restore the dump into a new volume with a temporary current-version container.

    The volume gets Compose's labels so that the shared services' Compose
    project adopts it. ``expected`` are the old cluster's databases and roles.
    The copy stays marked unfinished; :func:`copied_shared_postgres` removes
    the marker when the shared services switch to it.
    """
    container = f"docker exec -i {_POSTGRES_UPGRADE_CONTAINER}"
    executor.run(
        "docker volume create --label com.docker.compose.project=dallinger "
        f"--label com.docker.compose.volume=dallinger_pg{postgres.POSTGRES_MAJOR}_data "
        f"{_SERVER_POSTGRES_VOLUME} >/dev/null && "
        f"{_volume_file_command('touch', _COPY_IN_PROGRESS_MARKER)}"
    )
    mount = postgres.data_mount_path(postgres.POSTGRES_MAJOR)
    executor.run(
        f"docker run -d --name {_POSTGRES_UPGRADE_CONTAINER} "
        "-e POSTGRES_USER=dallinger -e POSTGRES_PASSWORD=dallinger "
        f"-e POSTGRES_DB=dallinger -v {_SERVER_POSTGRES_VOLUME}:{mount} "
        f"{postgres.POSTGRES_IMAGE} postgres -c jit=off"
    )
    # The image's first start initializes the cluster on a socket only, so
    # TCP answers once the final server runs.
    executor.run(
        "for i in $(seq 150); do "
        f"{container} pg_isready -h 127.0.0.1 -U dallinger >/dev/null 2>&1 "
        "&& exit 0; sleep 2; done; echo 'The new PostgreSQL did not start.' >&2; exit 1"
    )
    # Query results go to /dev/null, so that only psql's messages are left.
    output = executor.run(
        f"{container} psql -U dallinger -d postgres -q -o /dev/null "
        f"< {_POSTGRES_UPGRADE_DUMP} 2>&1"
    )
    lines = [
        line
        for line in (output or "").splitlines()
        if line.strip() and line not in _EXPECTED_RESTORE_ERRORS
    ]
    errors = [line for line in lines if not line.startswith(_RESTORE_NOTICE_PREFIXES)]
    if errors:
        raise click.ClickException(
            "Restoring the shared databases into PostgreSQL "
            f"{postgres.POSTGRES_MAJOR} failed: " + "; ".join(errors[:5])
        )
    if lines:
        print(
            f"PostgreSQL {postgres.POSTGRES_MAJOR} reported while restoring the "
            "shared databases: " + "; ".join(lines[:5])
        )
    copied = _cluster_contents(executor, container)
    if copied != expected:
        raise click.ClickException(
            "The copied databases and roles don't match the old ones: "
            f"expected {expected}, got {copied}."
        )
    _reset_role_passwords(executor, _POSTGRES_UPGRADE_CONTAINER, copied[1])
    executor.run(
        f"docker stop -t 60 {_POSTGRES_UPGRADE_CONTAINER} && "
        f"docker rm {_POSTGRES_UPGRADE_CONTAINER}"
    )


def _new_volume_state_script():
    """Return a shell script that prints ``copied``, ``unfinished`` or ``unrelated``.

    ``unfinished`` means the in-progress marker is present, or the volume
    holds no database. It wins over the finished-copy marker, which a switch
    cut off before it removed the in-progress one leaves too. ``copied``
    means the finished-copy marker is present next to PostgreSQL 18's data
    directory. Anything else initialized the volume some other way.
    """
    copied = f"/v/{_COPY_FINISHED_MARKER}"
    pending = f"/v/{_COPY_IN_PROGRESS_MARKER}"
    data = "/v/*/docker/PG_VERSION"
    return (
        f"if [ -f {pending} ] || ! ls {data} >/dev/null 2>&1; then echo unfinished; "
        f"elif [ -f {copied} ]; then echo copied; "
        "else echo unrelated; fi; true"
    )


def _volume_file_command(program, filename):
    """Return a command that runs ``program`` on ``filename`` in the new volume."""
    return (
        f"docker run --rm --entrypoint {program} -v {_SERVER_POSTGRES_VOLUME}:/v "
        f"{postgres.POSTGRES_IMAGE} /v/{filename}"
    )


def _seal_command():
    """Return the command that renames PG_VERSION in the old volume."""
    return (
        f"docker run --rm --entrypoint mv -v {_OLD_SERVER_POSTGRES_VOLUME}:/v "
        f"{postgres.POSTGRES_IMAGE} /v/PG_VERSION /v/{_SEALED_PG_VERSION}"
    )


def _seal_old_volume(executor, server):
    """Rename PG_VERSION in the old volume, so that PostgreSQL 12 can't start on it.

    See :data:`_SEALED_PG_VERSION`. The shared services are about to start on
    the copy, so a failure only warns; the next ``servers upgrade`` tries again.
    Returns whether the volume was sealed.
    """
    command = _seal_command()
    status, _, error = executor.run_with_status(command)
    if status != 0:
        print(
            f"{RED}Warning: could not seal the old volume "
            f"{_OLD_SERVER_POSTGRES_VOLUME}: {error.strip() or 'this failed'}.{END} "
            "Until it is sealed, a server compose file written back by an older "
            "Dallinger starts PostgreSQL 12 on the data from before the copy. "
            f"Run `dallinger docker-ssh servers upgrade --host {quote(server)}` "
            f"again, or run this on the server: `{command}`"
        )
    return status == 0


def _undo_shared_postgres_copy(executor, major):
    """Remove the copy and start the old shared Postgres again.

    Only safe before any app has written to the copy. Each step that fails
    is reported with the command to finish it by hand.
    """
    print(
        f"{RED}The shared database was not switched to PostgreSQL "
        f"{postgres.POSTGRES_MAJOR}, so the server is put back on PostgreSQL "
        f"{major}.{END}"
    )
    steps = (
        f"docker rm -f {_POSTGRES_UPGRADE_CONTAINER} >/dev/null 2>&1; "
        f"docker volume rm -f {_SERVER_POSTGRES_VOLUME}",
        f"{SERVER_COMPOSE} start postgresql",
    )
    for step in steps:
        status, _, error = executor.run_with_status(step)
        if status != 0:
            print(
                f"{RED}Warning: {error.strip() or 'this failed'}.{END} "
                f"Run it on the server: `{step}`"
            )


def _migrate_shared_postgres(executor, major, apps):
    """Copy the shared PostgreSQL ``major`` cluster into a current-version volume.

    Stops ``apps`` and the old Postgres so that nothing writes during the
    copy, dumps every database and role, and restores them into the new
    volume. The dump leaves out role passwords, whose MD5 hashes newer
    versions reject over the network, so they are set again (see
    :func:`_reset_role_passwords`). The old volume is not changed. If
    anything fails, the copy is undone, the apps are started again and the
    error is raised. ``apps`` maps the apps to stop to their running
    services. Returns
    the stopped ones, which the caller starts once the shared services run
    on the new version. If they don't get that far, the caller undoes the
    copy with :func:`_undo_shared_postgres_copy`.
    """
    old = f"{SERVER_COMPOSE} exec -T postgresql"
    stopped = {}
    try:
        # An interrupted run leaves the old Postgres stopped.
        executor.run(f"{SERVER_COMPOSE} start postgresql")
        executor.run(
            "for i in $(seq 30); do "
            f"{old} pg_isready -U dallinger >/dev/null 2>&1 && exit 0; sleep 2; "
            "done; echo 'The old PostgreSQL did not start.' >&2; exit 1"
        )
        _check_free_space(executor, old)
        for app, services in apps.items():
            print(f"Stopping {app}...")
            # Recorded first: a stop that fails may have stopped some services.
            stopped[app] = services
            executor.run(f"{_app_compose(app)} stop")
        # A wake that was under way can start a service again.
        running = [app for app in stopped if _running_services(executor, app)]
        if running:
            raise click.ClickException(
                f"These apps still run after being stopped: {', '.join(running)}."
            )
        print(f"Copying the shared PostgreSQL {major} databases...")
        expected = _cluster_contents(executor, old)
        # The new version's pg_dumpall, as PostgreSQL recommends: an older one
        # leaves out the old default privileges on schema public, which the
        # new version doesn't grant. Removing the old file first keeps a dump
        # that is still stopping writing to that file, not to this one.
        executor.run(
            f"docker rm -f {_POSTGRES_DUMP_CONTAINER} >/dev/null 2>&1; "
            f"rm -f {_POSTGRES_UPGRADE_DUMP} && "
            f"umask 077 && docker run --rm --name {_POSTGRES_DUMP_CONTAINER} --network "
            f"container:$({SERVER_COMPOSE} ps -q postgresql) -e PGPASSWORD=dallinger "
            f"{postgres.POSTGRES_IMAGE} pg_dumpall -h 127.0.0.1 -U dallinger "
            f"--no-role-passwords > {_POSTGRES_UPGRADE_DUMP}"
        )
        executor.run(f"{SERVER_COMPOSE} stop postgresql")
        _restore_shared_postgres(executor, expected)
    except BaseException:
        _undo_shared_postgres_copy(executor, major)
        _start_apps(executor, stopped)
        raise
    finally:
        executor.run(f"rm -f {_POSTGRES_UPGRADE_DUMP}", raise_=False)
    return stopped
