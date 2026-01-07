"""This module includes utilities to store and retrieve dallinger
configuration for the command line in the current user directory.
"""

import json
import shutil
from pathlib import Path
from typing import Dict

import click
import platformdirs

APPDIRS = platformdirs.PlatformDirs("dallinger", "dallinger")

# TODO: This NEW_HOSTS/OLD_HOSTS code dates from January 2026,
# and is present to maintain back-compatibility.
# Let's remove this in a future release, once we can be confident that users
# will have migrated to the new location.

# New location for storing docker-ssh servers
# (this new location is platform-independent and hence works better for DevContainers)
NEW_HOSTS_DIR = Path.home() / ".dallinger" / "docker-ssh" / "hosts"
# Old location (kept for backward compatibility when reading)
OLD_HOSTS_DIR = Path(APPDIRS.user_data_dir) / "hosts"


def _migrate_hosts_from_old_location():
    """Copy any hosts from the old location to the new location (if not already present)."""
    if not OLD_HOSTS_DIR.is_dir():
        return
    NEW_HOSTS_DIR.mkdir(parents=True, exist_ok=True)
    for host_file in OLD_HOSTS_DIR.iterdir():
        if not host_file.is_file():
            continue
        if (NEW_HOSTS_DIR / host_file.name).exists():
            continue
        shutil.copy(host_file, NEW_HOSTS_DIR)
        click.echo(f"Migrated host '{host_file.name}' to new location: {NEW_HOSTS_DIR}")


def get_configured_hosts():
    """Look into the user preferences to enumerate the remote ssh hosts
    that were configured for use with dallinger.

    Reads from both the new location (~/.dallinger/docker-ssh/hosts) and
    the old location (platformdirs) for backward compatibility. If a host
    exists in both locations, the new location takes precedence.
    """
    _migrate_hosts_from_old_location()

    res = {}
    for hosts_dir in (OLD_HOSTS_DIR, NEW_HOSTS_DIR):
        if hosts_dir.is_dir():
            for host_file in hosts_dir.iterdir():
                if host_file.is_file():
                    res[host_file.name] = json.loads(host_file.read_text())
    return res


def store_host(host: Dict[str, str]):
    """Store the given ssh host info in the local user config."""
    if not NEW_HOSTS_DIR.is_dir():
        NEW_HOSTS_DIR.mkdir(parents=True)
    (NEW_HOSTS_DIR / host["host"]).write_text(json.dumps(host))


def remove_host(hostname: str):
    """Remove a host from the configured hosts list.

    Checks both the new and old locations for backward compatibility.
    """
    removed = False
    for hosts_dir in (OLD_HOSTS_DIR, NEW_HOSTS_DIR):
        host_path = hosts_dir / hostname
        if host_path.exists():
            host_path.unlink()
            removed = True

    if not removed:
        print(f"Host {hostname} not found")
