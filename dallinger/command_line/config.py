"""This module includes utilities to store and retrieve dallinger
configuration for the command line in the current user directory.
"""

import json
from pathlib import Path
from typing import Dict

import platformdirs

APPDIRS = platformdirs.PlatformDirs("dallinger", "dallinger")

# New location for storing docker-ssh servers
# (this new location is platform-independent and hence works better for DevContainers)
NEW_HOSTS_DIR = Path.home() / ".dallinger" / "docker-ssh" / "hosts"
# Old location (kept for backward compatibility when reading)
OLD_HOSTS_DIR = Path(APPDIRS.user_data_dir) / "hosts"


def get_configured_hosts():
    """Look into the user preferences to enumerate the remote ssh hosts
    that were configured for use with dallinger.

    Reads from both the new location (~/.dallinger/docker-ssh/hosts) and
    the old location (platformdirs) for backward compatibility. If a host
    exists in both locations, the new location takes precedence.
    """
    res = {}

    # Read from both locations: old first (for backward compatibility),
    # then new (overwrites any duplicates from old location)
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
