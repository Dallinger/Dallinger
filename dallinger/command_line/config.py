"""This module includes utilities to store and retrieve dallinger
configuration for the command line in the current user directory.
"""

import json
from pathlib import Path
from typing import Dict

from dallinger.command_line import appdirs

APPDIRS = appdirs.AppDirs("dallinger", "dallinger")


def get_configured_hosts():
    """Look into the user preferences to enumerate the remote ssh hosts
    that were configured for use with dallinger.
    """
    hosts_dir = Path(APPDIRS.user_data_dir) / "hosts"
    res = {}
    if not hosts_dir.is_dir():
        return res
    for host in hosts_dir.iterdir():
        res[host.name] = json.loads(host.read_text())
    return res


def store_host(host: Dict[str, str]):
    """Store the given ssh host info in the local user config."""
    hosts_dir = Path(APPDIRS.user_data_dir) / "hosts"
    if not hosts_dir.is_dir():
        hosts_dir.mkdir(parents=True)
    (hosts_dir / host["host"]).write_text(json.dumps(host))


def remove_host(hostname: str):
    host_path = Path(APPDIRS.user_data_dir) / "hosts" / hostname
    if host_path.exists():
        host_path.unlink()
    else:
        print(f"Host {hostname} not found")
