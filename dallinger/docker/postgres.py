"""The PostgreSQL image that Dallinger's Docker services run.

A PostgreSQL data directory only opens in the major version that created it,
so a volume keeps that version until its data is copied into a newer one.
From PostgreSQL 18 on, the official image also keeps its data in a
version-specific directory under ``/var/lib/postgresql`` and expects the
volume there; older images use ``/var/lib/postgresql/data``.

New services run :data:`POSTGRES_IMAGE`. Code that starts Postgres on a volume
that may already hold data asks :func:`volume_major_command` which version
wrote it and renders :func:`template_vars` for that version.

PsyNet's ``psynet services ensure`` starts the same local service from its
own copy of these values, because Dallinger is not one of PsyNet's core
dependencies; a PsyNet test fails when the two drift apart.
"""

import re
from shlex import quote

POSTGRES_MAJOR = 18
POSTGRES_IMAGE = f"postgres:{POSTGRES_MAJOR}-trixie"

#: Name of the container and volume that ``dallinger docker start-services``
#: runs. The volume name carries the major version, so a volume written by an
#: older version is left alone instead of being opened by a newer one.
LOCAL_POSTGRES_CONTAINER = "dallinger_postgres"
LOCAL_POSTGRES_VOLUME = f"dallinger_postgres{POSTGRES_MAJOR}"


def image_for_major(major):
    """Return the image to run for data written by PostgreSQL ``major``."""
    return POSTGRES_IMAGE if major == POSTGRES_MAJOR else f"postgres:{major}"


def data_mount_path(major):
    """Return where a volume for PostgreSQL ``major`` is mounted in its container."""
    return "/var/lib/postgresql" if major >= 18 else "/var/lib/postgresql/data"


def template_vars(major=POSTGRES_MAJOR):
    """Return the Compose template variables for PostgreSQL ``major``."""
    return {
        "postgres_major": major,
        "postgres_image": image_for_major(major),
        "postgres_data_path": data_mount_path(major),
    }


def volume_major_command(volume):
    """Return a shell command that prints the PostgreSQL major version of ``volume``.

    The command prints nothing if the volume does not exist or holds no
    database, and fails if Docker can't tell, so that a caller never mistakes
    an unreadable volume for a missing one. It checks first because
    ``docker run`` would create a missing volume.
    """
    script = "cat /v/PG_VERSION /v/*/docker/PG_VERSION 2>/dev/null; true"
    return (
        "volumes=$(docker volume ls -q) || exit 1; "
        f"if printf '%s\\n' \"$volumes\" | grep -qxF {quote(volume)}; then "
        f"docker run --rm --entrypoint sh -v {quote(volume)}:/v:ro "
        f"{POSTGRES_IMAGE} -c {quote(script)}; fi"
    )


def parse_major(output):
    """Return the major version printed by :func:`volume_major_command`, or None.

    Raises ``ValueError`` if the volume holds data of several versions.
    """
    majors = {int(m) for m in re.findall(r"^\s*(\d+)\s*$", output or "", re.M)}
    if len(majors) > 1:
        raise ValueError(
            f"the volume holds data of PostgreSQL {sorted(majors)}, "
            "so its version is ambiguous"
        )
    return majors.pop() if majors else None
