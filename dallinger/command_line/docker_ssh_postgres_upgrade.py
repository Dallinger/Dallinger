"""Copy a docker-ssh server's shared PostgreSQL into a newer major version.

PostgreSQL only opens a data directory in the major version that created it,
so when :data:`dallinger.docker.postgres.POSTGRES_MAJOR` rises, the shared
Postgres of a classic-ingress server needs its databases copied into a new
volume. ``dallinger docker-ssh servers upgrade`` does that through
:func:`planned_copy` and :func:`copied_shared_postgres`; nothing else here is
meant to be called from outside.

The copy stops the server's classic apps, dumps every database and role with
the new version's ``pg_dumpall``, restores them into a temporary container on
the new volume and sets the apps' passwords again. The old volume is never
changed, and a copy that fails before the shared services switch to it is
undone. This module only handles the PostgreSQL 12 volume of Dallinger 13.0
and earlier, so it can be deleted, with its tests, once no such server is
left.
"""

from contextlib import contextmanager
from dataclasses import dataclass
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
# Kept in the new volume while the copy is made, so that a copy left by an
# interrupted run is recognized. A volume that the shared services created
# never has it.
_POSTGRES_COPY_MARKER = ".dallinger-copy-in-progress"
# A dump restored into a fresh cluster recreates the cluster's own owner and
# database, which initdb already made.
_EXPECTED_RESTORE_ERRORS = (
    'ERROR:  role "dallinger" already exists',
    'ERROR:  database "dallinger" already exists',
)
# Room for the new cluster's WAL and catalogs beyond the dump and the data.
_COPY_SPARE_BYTES = 256 * 2**20
# The password comes from the environment, which, unlike arguments, other
# users can't see in ``ps``. psql quotes the variables it substitutes, so it
# needs no escaping.
_RESET_PASSWORD_SQL = "\\getenv pw pw\nALTER ROLE :\"app\" PASSWORD :'pw';"


def _shared_postgres_to_migrate(executor):
    """Return the major version of a shared database still to be copied, or None.

    That is an older PostgreSQL's database in the volume that Dallinger 13.0
    and earlier set up, on a server without the current version's volume.
    Such a volume is a finished copy or was set up by this version, unless
    it holds no database or the marker of an unfinished copy. That is
    refused with the commands that remove it, because only the operator can
    tell that nothing uses it.
    """
    volumes = set(executor.run("docker volume ls -q").split())
    if _OLD_SERVER_POSTGRES_VOLUME not in volumes:
        return None
    major = _volume_major(executor, _OLD_SERVER_POSTGRES_VOLUME)
    if major is None or major == postgres.POSTGRES_MAJOR:
        return None
    if _SERVER_POSTGRES_VOLUME not in volumes:
        return major
    check = (
        f"test -f /v/{_POSTGRES_COPY_MARKER} || ! ls /v/*/docker/PG_VERSION "
        ">/dev/null 2>&1 && echo unfinished; true"
    )
    status = executor.run(
        f"docker run --rm --entrypoint sh -v {_SERVER_POSTGRES_VOLUME}:/v:ro "
        f"{postgres.POSTGRES_IMAGE} -c {quote(check)}"
    )
    if status.strip() != "unfinished":
        return None
    raise click.ClickException(
        f"The volume {_SERVER_POSTGRES_VOLUME} holds no database or an unfinished "
        "copy of the shared database, left by an interrupted `servers upgrade`; "
        f"the old volume {_OLD_SERVER_POSTGRES_VOLUME} is unchanged. Remove the "
        f"copy on the server with `docker rm -f {_POSTGRES_UPGRADE_CONTAINER}; "
        f"docker volume rm {_SERVER_POSTGRES_VOLUME}`, then run this command again. "
        "Apps that the interrupted run stopped stay stopped; once the copy is done, "
        "start each with `docker compose -f ~/dallinger/<app>/docker-compose.yml start`."
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

    ``major`` is the old cluster's version; ``apps`` maps each classic app to
    stop to its running services.
    """

    major: int
    apps: dict

    def describe(self):
        """Explain the copy before ``servers upgrade`` asks to continue."""
        print(
            f"The shared PostgreSQL moves from version {self.major} to "
            f"{postgres.POSTGRES_MAJOR}. Its databases are copied into the new "
            f"volume {_SERVER_POSTGRES_VOLUME}; the old volume "
            f"{_OLD_SERVER_POSTGRES_VOLUME} is kept unchanged."
        )
        if self.apps:
            print(
                "These classic apps are stopped during the copy, and the services "
                f"that ran are started again afterwards: {', '.join(self.apps)}."
            )


def planned_copy(server, executor):
    """Return the :class:`SharedPostgresCopy` that ``server`` needs, or None."""
    major = _shared_postgres_to_migrate(executor)
    if major is None:
        return None
    return SharedPostgresCopy(major, _classic_apps_to_stop(server, executor))


@contextmanager
def copied_shared_postgres(executor, server, copy):
    """Make ``copy``, if any, then let the caller switch the shared services to it.

    Yields a function that the caller calls right before it starts the shared
    services on the new version. From then on apps may write to the copy, so
    a failure keeps it; a failure before that undoes it. The stopped apps are
    started again either way.
    """
    if copy is None:
        yield lambda: None
        return
    stopped = _migrate_shared_postgres(executor, copy.major, copy.apps)
    switched = False

    def switch():
        nonlocal switched
        switched = True

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
        f"{postgres.POSTGRES_MAJOR}. Once the apps work, remove the old volume "
        f"on the server with `docker volume rm {_OLD_SERVER_POSTGRES_VOLUME}`."
    )


def _app_compose(app):
    return f"docker compose -f ~/dallinger/{quote(app)}/docker-compose.yml"


def _start_apps(executor, apps):
    """Start the services that :func:`_migrate_shared_postgres` stopped.

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
    The copy is marked unfinished until the temporary container is gone.
    """
    container = f"docker exec -i {_POSTGRES_UPGRADE_CONTAINER}"
    marker = f"/v/{_POSTGRES_COPY_MARKER}"
    on_volume = f"-v {_SERVER_POSTGRES_VOLUME}:/v {postgres.POSTGRES_IMAGE}"
    executor.run(
        "docker volume create --label com.docker.compose.project=dallinger "
        f"--label com.docker.compose.volume=dallinger_pg{postgres.POSTGRES_MAJOR}_data "
        f"{_SERVER_POSTGRES_VOLUME} >/dev/null && "
        f"docker run --rm --entrypoint touch {on_volume} {marker}"
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
    output = executor.run(
        f"{container} psql -U dallinger -d postgres -q < {_POSTGRES_UPGRADE_DUMP} 2>&1"
    )
    errors = [
        line
        for line in (output or "").splitlines()
        if line.startswith("ERROR:") and line not in _EXPECTED_RESTORE_ERRORS
    ]
    if errors:
        raise click.ClickException(
            "Restoring the shared databases into PostgreSQL "
            f"{postgres.POSTGRES_MAJOR} failed: " + "; ".join(errors[:5])
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
    executor.run(f"docker run --rm --entrypoint rm {on_volume} {marker}")


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
    :func:`_reset_role_passwords`). The old volume is never changed. If
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
        # new version doesn't grant.
        executor.run(
            "umask 077 && docker run --rm --network "
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
