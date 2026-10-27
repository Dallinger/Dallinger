import base64
import hashlib
import io
import ipaddress
import json
import logging
import os
import re
import secrets
import select
import socket
import subprocess
import sys
import threading
import warnings
import zipfile
from contextlib import ExitStack, contextmanager, redirect_stdout
from dataclasses import dataclass
from email.utils import parseaddr
from functools import wraps
from getpass import getuser
from io import BytesIO
from pathlib import Path, PurePosixPath
from secrets import token_urlsafe
from shlex import quote
from socket import gethostbyname_ex, gethostname
from typing import Dict, Literal
from urllib.parse import quote as url_quote
from uuid import uuid4

import click
import paramiko
import requests
from jinja2 import Environment, FileSystemLoader, Template
from requests.adapters import HTTPAdapter
from rich.text import Text
from urllib3.util.retry import Retry
from yaspin import yaspin

from dallinger.command_line.config import get_configured_hosts, remove_host, store_host
from dallinger.command_line.utils import (
    Output,
    get_experiment_files,
    render_rich_table,
    run_pre_launch_checks,
)
from dallinger.config import get_config
from dallinger.data import bootstrap_db_from_zip, export_db_uri
from dallinger.db import create_db_engine
from dallinger.deployment import setup_experiment
from dallinger.hibernation import STATE_HIBERNATING as HIBERNATING
from dallinger.hibernation import STATE_WAKING as WAKING
from dallinger.utils import (
    BLUE,
    END,
    GREEN,
    JSON_LOGFILE,
    RED,
    abspath_from_egg,
    print_bold,
)

from .lib.app_manifest import (
    APP_NAME_PATTERN,
    INGRESS_CLASSIC,
    INGRESS_CLOUDFLARE,
    DeploymentManifest,
    public_origin_for_hostname,
    remote_manifest_path,
)
from .lib.cloudflare import (
    CloudflareError,
    delete_experiment_tunnel,
    ensure_experiment_tunnel,
    load_api_token,
    public_resource_ids,
    tunnel_name_for_app,
    validate_app_dns_label,
)
from .lib.cloudflare import config_str as cloudflare_config_str
from .lib.cloudflare import public_hostname as cloudflare_public_hostname
from .lib.launch import (
    LaunchTarget,
    check_internal_health,
    launch_from_server,
    ssh_command,
    wait_for_public_url,
)
from .utils import get_server_pem_path

# Hibernated apps keep stopped Compose containers that ``awaken`` restarts.
CONTAINER_PRUNE = "docker container prune -f --filter label!=com.docker.compose.project"
SERVER_COMPOSE = "docker compose -f ~/dallinger/docker-compose.yml"
# Databases in the shared Postgres that are never an app's own.
SHARED_POSTGRES_DATABASES = {"dallinger", "postgres", "template0", "template1"}


@dataclass(frozen=True)
class App:
    """A discovered remote docker-ssh app and its runtime state.

    Parameters
    ----------
    name : str
        App/project name on the remote server.
    state : Literal["running", "inactive", "hibernating", "waking"]
        Runtime state label used by CLI output and app selection logic.
    ingress : str
        ``classic`` host Caddy or ``cloudflare`` per-app tunnel.
    public_origin : str or None
        HTTPS origin when known from a deployment manifest.
    """

    name: str
    state: Literal["running", "inactive", "hibernating", "waking"]
    ingress: str = "classic"
    public_origin: str | None = None


# Find an identifier for the current user to use as CREATOR of the experiment
HOSTNAME = gethostname()
try:
    USER = getuser()
except (KeyError, OSError):  # Python >= 3.13 raises OSError
    USER = "user"

DOCKER_COMPOSE_SERVER_TPL = Template(
    abspath_from_egg(
        "dallinger", "dallinger/docker/ssh_templates/docker-compose-server.yml.j2"
    ).read_text()
)

_SSH_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(
        abspath_from_egg(
            "dallinger",
            "dallinger/docker/ssh_templates/docker-compose-experiment.yml.j2",
        ).parent
    ),
    autoescape=False,
)
DOCKER_COMPOSE_EXP_TPL = _SSH_TEMPLATE_ENV.get_template(
    "docker-compose-experiment.yml.j2"
)

FRONTDOOR_CADDYFILE = abspath_from_egg(
    "dallinger", "dallinger/docker/ssh_templates/Caddyfile.frontdoor"
).read_text()
HIBERNATION_CONTROLLER = abspath_from_egg(
    "dallinger", "dallinger/hibernation.py"
).read_text()


def _read_controller_image(dockerfile: Path | None) -> str:
    """Return the image named on the ``FROM`` line of ``Dockerfile.controller``."""
    if dockerfile is None:
        raise RuntimeError(
            "Dallinger's docker-ssh controller image file "
            "(dallinger/docker/ssh_templates/Dockerfile.controller) is missing."
        )
    match = re.search(r"(?m)^FROM\s+(\S+)", dockerfile.read_text())
    if match is None:
        raise RuntimeError(
            f"{dockerfile} has no FROM line naming the controller image."
        )
    return match.group(1)


CONTROLLER_IMAGE = _read_controller_image(
    abspath_from_egg(
        "dallinger", "dallinger/docker/ssh_templates/Dockerfile.controller"
    )
)


CADDYFILE_SUBDOMAIN = """
# This is a configuration file for the Caddy http Server
# Documentation can be found at https://caddyserver.com/docs
{{
    grace_period 30s
}}


{host} {{
    respond /health-check 200
    {tls}
}}

logs.{host} {{
    reverse_proxy dozzle:8080
    {tls}
}}

import caddy.d/*
"""


CADDYFILE_ROOT = """
# This is a configuration file for the Caddy http Server
# Documentation can be found at https://caddyserver.com/docs
{{
    grace_period 30s
}}


{host} {{
    {tls}
    handle /health-check {{
        respond 200
    }}
    handle /logs* {{
        reverse_proxy dozzle:8080
    }}
    handle {{
        reverse_proxy {backend}
    }}
}}
"""


@click.group()
@click.pass_context
def docker_ssh(ctx):
    """Deploy to a remote server using docker through ssh."""


@docker_ssh.group()
def servers():
    """Manage remote servers where experiments can be deployed"""


@servers.command(name="list")
def list_servers():
    if not CONFIGURED_HOSTS:
        print("No server configured. Use `dallinger docker-ssh servers add` to add one")
    for host in CONFIGURED_HOSTS.values():
        print(", ".join(f"{key}: {value}" for key, value in host.items()))


@servers.command()
@click.option(
    "--host", required=True, help="IP address or dns name of the remote server"
)
@click.option("--user", help="User to use when connecting to remote host")
@click.option(
    "--default-ingress",
    type=click.Choice([INGRESS_CLASSIC, INGRESS_CLOUDFLARE]),
    default=INGRESS_CLASSIC,
    show_default=True,
    help="Default participant ingress for deploys that omit --ingress",
)
def add(host, user, default_ingress):
    """Add a server to deploy experiments through ssh using docker.
    The server needs `docker` and `docker compose` usable by the current user.
    Classic Caddy ingress needs free ports 80 and 443. Cloudflare tunnel apps
    do not publish those ports.
    In case `docker` and/or `docker compose` are missing, dallinger will try to
    install them using `sudo`. The given user must have passwordless sudo rights.

    You can configure SSH authentication using a PEM file by setting the `server_pem`
    configuration variable in your config.txt or ~/.dallingerconfig:

    [Parameters]
    server_pem = ~/.ssh/your-key.pem

    Cloudflare tunnel apps also need ``cloudflare_account_id``,
    ``cloudflare_zone_id``, and ``cloudflare_dns_zone`` in Dallinger config.
    """
    prepare_server(host, user)
    store_host({"host": host, "user": user, "default_ingress": default_ingress})
    advice = default_ingress == INGRESS_CLASSIC and _private_network_advice(host, user)
    if advice:
        print(f"{RED}Warning: {advice}{END}")


@servers.command()
@click.option(
    "--host",
    required=False,
    default=None,
    callback=lambda ctx, param, value: resolve_server_option(ctx, param, value),
    type=str,
    help="IP address or dns name of the remote server",
)
def remove(host):
    """Remove server from list of known remote servers.
    No action is performed remotely.
    """
    remove_host(host)


def prepare_server(host, user):
    import paramiko.ssh_exception

    try:
        executor = Executor(host, user)
    except paramiko.ssh_exception.AuthenticationException as exc:
        if user is None:
            raise paramiko.ssh_exception.AuthenticationException(
                "Failed to authenticate to the server. Do you need to specify a user?"
            ) from exc
        raise

    with _spinner(text="Checking for Docker...", color="green") as sp:
        docker_installed = bool(executor.run("command -v docker", raise_=False).strip())
        if not docker_installed:
            sp.text = "Installing Docker..."
            executor.check_sudo()
            executor.run("wget -O - https://get.docker.com | sudo -n bash")
            executor, docker_usable = _grant_docker_group_and_refresh_session(
                executor, host, user, check_sudo=False
            )
            if not docker_usable:
                sp.fail("✖")
                raise click.ClickException(
                    "Docker installed, but it is still not usable by this user. "
                    "Ensure the Docker daemon is running and the user can access the Docker socket."
                )
            sp.ok("✔")
            return

        if _docker_is_usable(executor):
            sp.ok("✔")
            return

        sp.text = "Configuring Docker permissions..."
        executor, docker_usable = _grant_docker_group_and_refresh_session(
            executor, host, user
        )
        if docker_usable:
            sp.ok("✔")
            return

        sp.fail("✖")
        raise click.ClickException(
            "Docker is installed but not usable by this user. "
            "Ensure the Docker daemon is running and the user can access the Docker socket."
        )


def _docker_is_usable(executor):
    return (
        executor.run("docker ps >/dev/null 2>&1 && echo usable", raise_=False).strip()
        == "usable"
    )


def _grant_docker_group_and_refresh_session(executor, host, user, check_sudo=True):
    if check_sudo:
        executor.check_sudo()
    executor.run("sudo -n adduser $(id --user --name) docker")
    # Group membership only applies to new logins.
    _forget_ssh_client(host, user)
    refreshed_executor = Executor(host, user)
    return refreshed_executor, _docker_is_usable(refreshed_executor)


def copy_docker_config(host, user):
    executor = Executor(host, user)

    local_docker_conf_path = os.path.expanduser("~/.docker/config.json")
    if os.path.exists(local_docker_conf_path):
        with open(local_docker_conf_path, "rb") as fh:
            local_file_contents = fh.read()
        remote_has_conf = executor.run(
            "ls ~/.docker/config.json > /dev/null && echo true || true"
        ).strip()
        if remote_has_conf == "true":
            remote_sha, _ = executor.run("sha256sum ~/.docker/config.json").split()
            local_sha = hashlib.sha256(local_file_contents).hexdigest()
            if local_sha != remote_sha:
                # Move the remote file to a temporary location
                executor.run(
                    "mv ~/.docker/config.json  ~/.docker/config.json.$(date +%d-%m-%Y-%H:%M.bak)"
                ).split()
        sftp = get_sftp(host, user=user)
        try:
            # Create the .docker directory if it doesn't exist
            sftp.mkdir(".docker")
        except IOError:
            pass
        sftp.putfo(BytesIO(local_file_contents), ".docker/config.json")


CONFIGURED_HOSTS = get_configured_hosts()


def _is_ip_address(host):
    """Whether ``host`` (optionally ``host:port`` or ``[host]:port``) is an IP."""
    try:
        ipaddress.ip_address(split_ssh_host_port(host)[0])
    except (ValueError, click.UsageError):
        return False
    return True


def _short_name(host):
    """Return the label before the first dot of ``host``, ignoring any port.

    Returns None for IP addresses and malformed hosts.
    """
    if _is_ip_address(host):
        return None
    try:
        hostname = split_ssh_host_port(host)[0]
    except click.UsageError:
        return None
    return hostname.split(".", 1)[0]


def resolve_server_name(name, hosts):
    """Return the configured server that ``name`` refers to.

    Parameters
    ----------
    name : str
        A full configured server name, or its short hostname (the part before
        the first dot, without any port), e.g. ``rr-pc02`` for
        ``rr-pc02.example.ac.uk`` or ``pc04`` for ``pc04:2200``.
        Servers registered by IP address only match their full address.
    hosts : iterable of str
        Configured server names.

    Returns
    -------
    str
        The full configured server name.

    Raises
    ------
    ValueError
        If ``name`` matches no configured server, or is a short hostname
        shared by several of them.
    """
    hosts = tuple(hosts)
    if name in hosts:
        return name
    matches = [host for host in hosts if _short_name(host) == name]
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise ValueError(
            f"Server '{name}' is ambiguous. It matches: {', '.join(matches)}"
        )
    choices = ", ".join(hosts) if hosts else "<none>"
    raise ValueError(f"Unknown server '{name}'. Configured servers: {choices}")


def _complete_server_name(ctx, param, incomplete):
    return [host for host in get_configured_hosts() if host.startswith(incomplete)]


def resolve_server_option(ctx, param, value):
    hosts = tuple(get_configured_hosts().keys())
    option_name = (
        f"--{param.name.replace('_', '-')}" if param is not None else "--server"
    )
    action = ctx.command.name if ctx is not None and ctx.command is not None else None

    if value is not None:
        try:
            return resolve_server_name(value, hosts)
        except ValueError as exc:
            raise click.BadParameter(str(exc), param=param) from exc

    if len(hosts) == 1:
        return hosts[0]

    if len(hosts) == 0:
        raise click.UsageError(
            "No server configured. Use `dallinger docker-ssh servers add` to add one."
        )

    if ctx is not None and getattr(ctx, "resilient_parsing", False):
        return None

    if not sys.stdin.isatty():
        choices = ", ".join(hosts)
        raise click.UsageError(
            f"Please provide `{option_name}` in non-interactive mode. "
            f"Configured servers: {choices}"
        )

    if action == "remove":
        click.echo("Choose which configured server to remove:")
    else:
        click.echo(
            "Choose one of the configured servers "
            "(add one with `dallinger docker-ssh servers add`):"
        )
    for idx, host in enumerate(hosts, start=1):
        click.echo(f"  {idx}) {host}")

    number_prompt = (
        "Select server number to remove"
        if action == "remove"
        else "Select server number"
    )
    selected_idx = click.prompt(number_prompt, type=click.IntRange(1, len(hosts)))
    return hosts[selected_idx - 1]


# Click options
option_app_name = click.option(
    "--app",
    "app_name",
    help="Name to use for the app. If not provided a random one will be generated",
)
option_archive = click.option(
    "--archive",
    "-a",
    "archive_path",
    type=click.Path(exists=True),
    help="Path to a zip archive created with the `export` command to use as initial database state",
)
option_config = click.option("--config", "-c", "config_options", nargs=2, multiple=True)
option_dns_host = click.option(
    "--dns-host",
    help="Classic Caddy DNS name. Must resolve all its subdomains to the IP address "
    "specified as ssh host. Not used for Cloudflare apps. You can use 'nip.io' to "
    "automatically generate a nip.io domain from the server's IP address.",
)
option_server = click.option(
    "--server",
    required=False,
    default=None,
    help="Name of the remote server, or its short hostname "
    "(see `dallinger docker-ssh servers list`)",
    type=str,
    shell_complete=_complete_server_name,
    callback=resolve_server_option,
)
option_update = click.option(
    "--update",
    "-u",
    is_flag=True,
    default=False,
    help="Update an existing experiment",
)
option_local_build = click.option(
    "--local_build",
    is_flag=True,
    default=False,
    help="Build the Docker image locally instead of on the remote server.",
)
option_push_build = click.option(
    "--push-build",
    is_flag=True,
    default=False,
    help="Push the built image to a registry. This option is selected automatically if --local-build is used.",
)
option_ingress = click.option(
    "--ingress",
    type=click.Choice([INGRESS_CLASSIC, INGRESS_CLOUDFLARE]),
    default=None,
    help=(
        "How participants reach the experiment: classic host Caddy or a per-app "
        "Cloudflare tunnel. Defaults to the server's default_ingress, or classic."
    ),
)
option_allow_private_ip = click.option(
    "--allow-private-ip",
    is_flag=True,
    default=False,
    help=(
        "Deploy with classic ingress even though the SSH host resolves to a "
        "private IP address, for servers whose public DNS name points at a "
        "public IP that forwards ports 80 and 443 to them. The experiment "
        "hostname must still resolve, but is not compared with the SSH host's "
        "address."
    ),
)
# Hidden because only callers that read the returned dict, via
# ``ctx.invoke(..., show_summary=False)``, can use the details it hides.
option_show_summary = click.option(
    "--summary/--no-summary",
    "show_summary",
    default=True,
    hidden=True,
    help=(
        "Print the closing summary: links, logs command, dashboard password "
        "and recruitment message."
    ),
)
option_deploy_delete_data_command = click.option(
    "--delete-data-command",
    hidden=True,
    help=(
        "Command printed for deleting the kept data of apps that a root-domain "
        "deploy destroys, with {app} standing for the app name, for tools that "
        "wrap this command."
    ),
)


def should_use_subdomain(app_name, archive_path):
    if app_name:
        return True
    if archive_path:
        return False
    return False


def split_ssh_host_port(host):
    """Parse SSH host strings into ``(host, port)``.

    Accepts unbracketed hosts in ``host`` or ``host:port`` form, and
    bracketed IPv6 hosts in ``[host]`` or ``[host]:port`` form.
    If no port is provided, defaults to 22.

    Examples
    --------
    >>> split_ssh_host_port("example.com")
    ('example.com', 22)
    >>> split_ssh_host_port("localhost:2222")
    ('localhost', 2222)
    >>> split_ssh_host_port("[::1]:2200")
    ('::1', 2200)
    """
    host = host.strip()
    if not host:
        raise click.UsageError("Invalid host format ''. Use host or host:port.")

    def _parse_port(port_text):
        if not port_text.isdigit():
            raise click.UsageError(
                f"Invalid host format '{host}'. Use host or host:port."
            )
        parsed_port = int(port_text)
        if parsed_port < 1 or parsed_port > 65535:
            raise click.UsageError(
                f"Invalid port '{parsed_port}' in host '{host}'. Port must be between 1 and 65535."
            )
        return parsed_port

    if host.startswith("["):
        bracket_end = host.find("]")
        if bracket_end == -1:
            raise click.UsageError(
                f"Invalid host format '{host}'. Use host or host:port."
            )
        parsed_host = host[1:bracket_end]
        if not parsed_host:
            raise click.UsageError(
                f"Invalid host format '{host}'. Use host or host:port."
            )
        suffix = host[bracket_end + 1 :]
        if not suffix:
            return parsed_host, 22
        if suffix.startswith(":"):
            return parsed_host, _parse_port(suffix[1:])
        raise click.UsageError(f"Invalid host format '{host}'. Use host or host:port.")

    if host.count(":") == 1:
        parsed_host, port_candidate = host.rsplit(":", 1)
        if not parsed_host:
            raise click.UsageError(
                f"Invalid host format '{host}'. Use host or host:port."
            )
        return parsed_host, _parse_port(port_candidate)

    if host.count(":") > 1:
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise click.UsageError(
                f"Invalid host format '{host}'. Use host or host:port."
            ) from exc

    return host, 22


def is_loopback_host(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def known_hosts_target(host, port):
    return host if port == 22 else f"[{host}]:{port}"


def docker_host_uri(host, user=None, port=22):
    """Return a DOCKER_HOST SSH URL for the remote Docker daemon.

    docker-py splits this URL on ``@`` and cannot parse a username that
    itself contains ``@``, such as a Cambridge CRSid login. Those users are
    left out of the URL, so the SSH client chooses the user (usually from
    ``~/.ssh/config``); a hint is printed unless ``ssh -G`` reports that it
    would already log in as that user.
    """
    ssh_host = host
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if user and "@" in user:
        if _ssh_config_user(ssh_host, port) != user:
            print(
                f"SSH user {user!r} contains '@', so Docker connects without it. "
                f"Set `User {user}` for {ssh_host} in ~/.ssh/config."
            )
        user = None
    user_part = f"{user}@" if user else ""
    port_part = f":{port}" if port != 22 else ""
    return f"ssh://{user_part}{host}{port_part}"


def _ssh_config_user(host, port=None):
    """Return the user OpenSSH would log in to ``host`` as, or None if unknown.

    Docker's SSH transport runs ``ssh``, so ``ssh -G`` answers for exactly
    the configuration it uses (``Include``, ``Match`` and system files too).
    """
    return (_ssh_config(host, port) or {}).get("user", [None])[0]


def _ssh_config(host, port=None):
    """Return the options ``ssh -G`` resolves for ``host``, or None if unknown.

    Parameters
    ----------
    host : str
        The host name or SSH alias.
    port : int, optional
        The port to connect to, passed as ``-p``. By default, the one the
        SSH config gives.

    Returns
    -------
    dict or None
        Lower-case option names mapped to lists of values, such as
        ``{"user": ["alice"], "identityfile": ["~/.ssh/id_rsa", ...]}``.
    """
    port_args = [] if port is None else ["-p", str(port)]
    try:
        result = subprocess.run(
            ["ssh", "-G", *port_args, "--", host],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logging.getLogger(__name__).debug("ssh -G %s failed: %s", host, exc)
        return None
    if result.returncode != 0:
        return None
    options = {}
    for line in result.stdout.splitlines():
        key, _, value = line.partition(" ")
        options.setdefault(key, []).append(value)
    return options


def _resolve_server_info(server):
    return CONFIGURED_HOSTS[resolve_server_name(server, CONFIGURED_HOSTS)]


def _build_executor(server_info, app=None):
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")
    return Executor(ssh_host, user=ssh_user, app=app)


def _executor_for_server(server, app=None):
    server_info = _resolve_server_info(server)
    return _build_executor(server_info, app=app)


def _discover_server_apps(executor):
    existing = set()

    listing = executor.run(
        "ls -1 ~/dallinger/caddy.d 2>/dev/null || true; "
        "ls -1 ~/dallinger/*/docker-compose.yml 2>/dev/null || true",
        raise_=False,
    )
    for entry in listing.splitlines():
        if not entry:
            continue
        if entry.endswith("/docker-compose.yml"):
            existing.add(Path(entry).parent.name)
        else:
            existing.add(entry)

    return sorted(existing)


def _host_caddy_apps(executor):
    """Apps behind host Caddy; Cloudflare apps don't compete for the root domain."""
    apps = _discover_server_apps(executor)
    manifests = _load_remote_manifests(executor, apps)
    return [
        app
        for app in apps
        if app not in manifests or manifests[app].ingress != INGRESS_CLOUDFLARE
    ]


def _load_remote_manifests(executor, app_names):
    """Read ``deployment.json`` for the given apps in one SSH call.

    Each file is printed as one ``<app><TAB><json>`` line. Names that are not
    valid app names (for example stray files) are skipped, not sent to the shell.
    """
    app_names = [name for name in app_names if APP_NAME_PATTERN.fullmatch(name)]
    if not app_names:
        return {}
    raw = executor.run(
        f"for app in {' '.join(app_names)}; do f=~/dallinger/$app/deployment.json; "
        '[ -f "$f" ] && printf "%s\\t" "$app" && tr -d "\\n" < "$f" && echo; done; true',
        raise_=False,
    )
    manifests = {}
    for line in (raw or "").splitlines():
        name, _, text = line.partition("\t")
        manifest = DeploymentManifest.from_json(text)
        if name in app_names and manifest is not None:
            manifests[name] = manifest
    return manifests


def _upload_app_manifest(sftp, manifest: DeploymentManifest) -> None:
    """Write ``deployment.json`` next to the app Compose file. Never logs secrets."""
    sftp.putfo(
        BytesIO(manifest.to_json().encode()),
        remote_manifest_path(manifest.app),
    )


def _monitoring_settings(config_map):
    """Return generic monitoring kind and path for a deployment manifest."""
    kind = str(config_map.get("docker_ssh_monitoring_kind") or "experiment").strip()
    path = str(config_map.get("docker_ssh_monitoring_path") or "/health").strip()
    return kind or "experiment", path or "/health"


def _root_domain_preflight_required(server, app_name, archive_path, ingress):
    """Return whether this deploy would take over the host Caddy root site.

    Cloudflare apps use ``{app}.{zone}`` even when ``--app`` is omitted, so
    they must not offer to destroy every experiment on the server.
    """
    if should_use_subdomain(app_name, archive_path):
        return False
    try:
        server_info = _resolve_server_info(server)
    except ValueError:
        server_info = {}
    if _resolve_ingress(server_info, ingress) == INGRESS_CLOUDFLARE:
        return False
    return True


def _resolve_ingress(server_info, ingress=None):
    """Return classic or cloudflare from --ingress or the host record."""
    requested = ingress or server_info.get("default_ingress") or INGRESS_CLASSIC
    requested = str(requested).strip().lower()
    if requested not in {INGRESS_CLASSIC, INGRESS_CLOUDFLARE}:
        raise click.UsageError(
            f"Unknown ingress mode {requested!r}; expected classic or cloudflare."
        )
    return requested


def _private_network_advice(host, user):
    """Return advice against classic ingress if ``host`` has no public IPv4 address.

    ``host`` may include an SSH port. Loopback and unspecified (``0.0.0.0``)
    addresses count as public, for servers that are tunnelled to locally.
    """
    ip_addrs = _ipv4_addresses(split_ssh_host_port(host)[0])
    for ip_addr in ip_addrs:
        address = ipaddress.ip_address(ip_addr)
        if address.is_global or address.is_loopback or address.is_unspecified:
            return None
    if not ip_addrs:
        return None
    ip_addr = ip_addrs[0]
    user_option = f" --user {user}" if user else ""
    return (
        f"{host} has a private IP address ({ip_addr}), so Let's Encrypt cannot "
        "issue TLS certificates for it and participants outside its network "
        "cannot reach classic ingress. Deploy with --ingress cloudflare, or "
        "re-register the server with `dallinger docker-ssh servers add "
        f"--host {host}{user_option} --default-ingress cloudflare`. If the "
        "server's public DNS name points at a public IP that forwards ports 80 "
        "and 443 to it, deploy with --allow-private-ip instead."
    )


def _check_classic_ingress_reachable(server, ingress=None):
    """Abort classic-ingress deploys to servers on a private network."""
    server_info = CONFIGURED_HOSTS.get(server) or {}
    if _resolve_ingress(server_info, ingress) == INGRESS_CLOUDFLARE:
        return
    advice = _private_network_advice(
        server_info.get("host", server), server_info.get("user")
    )
    if advice:
        raise click.ClickException(advice)


def _cloudflare_settings(config, dns_zone=None):
    """Read non-secret Cloudflare account/zone settings from Dallinger config.

    ``--dns-host`` is a classic Caddy hostname and is never used as the
    Cloudflare DNS zone. ``dns_zone`` overrides config (destroy passes the
    zone recorded in the manifest).
    """
    account_id = cloudflare_config_str(config, "cloudflare_account_id")
    zone_id = cloudflare_config_str(config, "cloudflare_zone_id")
    dns_zone = str(dns_zone or config.get("cloudflare_dns_zone", "") or "")
    dns_zone = dns_zone.strip().lower().rstrip(".")
    missing = [
        name
        for name, value in (
            ("cloudflare account id", account_id),
            ("cloudflare zone id", zone_id),
            ("DNS zone", dns_zone),
        )
        if not value
    ]
    if missing:
        raise click.UsageError(
            "Cloudflare docker-ssh deploys need "
            + ", ".join(missing)
            + ". Set cloudflare_account_id, cloudflare_zone_id, and "
            "cloudflare_dns_zone in Dallinger config."
        )
    return {
        "account_id": account_id,
        "zone_id": zone_id,
        "dns_zone": dns_zone,
    }


def _is_true(value):
    """Return whether a config value, possibly a CLI string, is true."""
    return str(value).lower() in {"true", "1", "yes"}


def _idle_settings(config_map):
    """Return idle hibernation flag and minutes from a compose/config mapping."""
    enabled = _is_true(config_map.get("docker_ssh_idle_hibernate", False))
    try:
        minutes = int(config_map.get("docker_ssh_idle_hibernate_minutes") or 60)
    except (TypeError, ValueError):
        minutes = 60
    return enabled, max(minutes, 1)


def _existing_app_secret(executor, app, key):
    """Return ``key`` from the app's ``.env``, where deploy keeps its secrets."""
    env = executor.run(f"cat ~/dallinger/{app}/.env", raise_=False) or ""
    for line in env.splitlines():
        name, _, value = line.partition("=")
        if name == key and value:
            return value
    return None


def _app_secrets(executor, app, update):
    """Return the secrets for the app's ``.env``, keeping existing ones on update.

    Keeping ``FLASK_SECRET_KEY`` keeps participants' sessions valid.
    """
    return {
        key: (update and _existing_app_secret(executor, app, key)) or token_urlsafe(16)
        for key in ("POSTGRES_PASSWORD", "FLASK_SECRET_KEY")
    }


def _upload_frontdoor_caddyfile(sftp, executor, app):
    """Install the front-door Caddyfile, the controller script, and the state dir."""
    executor.run(f"mkdir -p ~/dallinger/{app}/state")
    sftp.putfo(
        BytesIO(FRONTDOOR_CADDYFILE.encode()),
        f"dallinger/{app}/Caddyfile.frontdoor",
    )
    sftp.putfo(
        BytesIO(HIBERNATION_CONTROLLER.encode()), f"dallinger/{app}/hibernation.py"
    )


def _project_siblings(app, server_apps):
    """Return the other ``server_apps`` whose Compose project is ``app``'s.

    Such apps (for example ``MyApp`` and ``myapp``) share containers and
    volumes. Entries that are not valid app names are not apps.
    """
    project = _compose_project(app)
    return [
        name
        for name in server_apps
        if name != app
        and APP_NAME_PATTERN.fullmatch(name)
        and _compose_project(name) == project
    ]


def _check_compose_project_free(executor, app, update):
    """Abort if another app on the server has ``app``'s Compose project name."""
    server_apps = _discover_server_apps(executor)
    siblings = _project_siblings(app, server_apps)
    if siblings:
        others = ", ".join(siblings)
        if not update:
            advice = f"Use a different name, or destroy {others} first."
        elif app in server_apps:
            # While app exists, destroy refuses to delete the other app's data.
            advice = (
                f"Destroy {others} first with --keep-data; this also stops the "
                f"containers of {app}, which share the project, until this "
                "update starts them again."
            )
        else:
            advice = f"There is no app {app} to update; did you mean {others}?"
        print(
            f"{RED}App name {app} gives the same Docker Compose project, "
            f"{_compose_project(app)}, as the existing "
            f"app{'s' if len(siblings) > 1 else ''} {others}, so they would share "
            f"containers and volumes. {advice}{END}"
        )
        raise click.Abort()


def _check_app_slot(executor, app, update, ingress):
    """Abort unless ``app`` is free, or exists with this ingress for ``--update``.

    The manifest records ingress; apps deployed before manifests are classic.
    """
    compose_path = f"~/dallinger/{app}/docker-compose.yml"
    if update:
        if not executor.run(f"ls {compose_path}", raise_=False):
            print(
                f"{compose_path} file not found. App {app} does not exist on the server."
            )
            raise click.Abort()
        manifest = _load_remote_manifests(executor, [app]).get(app)
        existing_ingress = manifest.ingress if manifest else INGRESS_CLASSIC
        if existing_ingress != ingress:
            print(
                f"{RED}App {app} is a {existing_ingress} deploy. "
                f"Destroy it before redeploying it with {ingress} ingress.{END}"
            )
            raise click.Abort()
        return
    found = [
        path
        for path in (compose_path, f"~/dallinger/caddy.d/{app}")
        if executor.run(f"ls {path}", raise_=False)
    ]
    if found:
        print(
            f"App with name {app} already exists: found {', '.join(found)}. "
            "Use a different name, destroy the current app, or add --update"
        )
        raise click.Abort()


def _upload_app_stack(
    sftp,
    executor,
    cfg,
    *,
    app,
    server,
    public_origin,
    image_name,
    ingress,
    secrets,
    cloudflare=None,
):
    """Upload the app's Compose file, its secrets, and the non-secret manifest.

    Compose reads ``secrets`` (for example ``POSTGRES_PASSWORD``) from the
    app's ``.env``, so the Compose file itself holds none.

    Returns the image the replaced Compose file pinned, or None for a new app.
    """
    previous_image = read_remote_experiment_image(executor, app)
    # The JSON log is bind-mounted as a file, so it must exist before Compose starts.
    executor.run(f"mkdir -p dallinger/{app} && touch dallinger/{app}/{JSON_LOGFILE}")
    run_as_ssh_user = _image_runs_as_ssh_user(executor, image_name)
    sftp.putfo(
        BytesIO(
            get_docker_compose_yml(
                cfg, app, image_name, ingress, run_as_ssh_user=run_as_ssh_user
            ).encode()
        ),
        f"dallinger/{app}/docker-compose.yml",
    )
    # Other config values in the Compose file, such as the dashboard
    # password, are still sensitive.
    sftp.chmod(f"dallinger/{app}/docker-compose.yml", 0o600)
    _write_app_env(sftp, executor, app, secrets)
    _write_experiment_compose_env(executor, app, cfg.get("docker_volumes", ""))
    _upload_frontdoor_caddyfile(sftp, executor, app)
    monitoring_kind, monitoring_path = _monitoring_settings(cfg)
    _upload_app_manifest(
        sftp,
        DeploymentManifest(
            app=app,
            server=server,
            public_origin=public_origin,
            ingress=ingress,
            monitoring_kind=monitoring_kind,
            monitoring_path=monitoring_path,
            cloudflare=cloudflare or {},
        ),
    )
    return previous_image


def _remove_replaced_image(executor, app, previous_image, image_name):
    """After an update, remove the app's previous image unless another app pins it.

    The update has already succeeded, so a cleanup failure only warns.
    """
    if not previous_image or previous_image == image_name:
        return
    try:
        remove_unshared_experiment_image(executor, previous_image, except_app=app)
    except Exception as exc:
        print(f"Warning: could not remove the previous image {previous_image}: {exc}")


def _image_runs_as_ssh_user(executor, image_name):
    """Return whether the image was built to run as the SSH user.

    Images built before that change have a root-owned ``/experiment`` that
    the SSH user cannot write, so they keep running as root.
    """
    from dallinger.docker.tools import RUNS_AS_SSH_USER_LABEL

    image = quote(image_name)
    label = executor.run(
        f"docker pull -q {image} >/dev/null 2>&1; docker image inspect -f "
        f"'{{{{index .Config.Labels \"{RUNS_AS_SSH_USER_LABEL}\"}}}}' {image}",
        raise_=False,
    )
    if (label or "").strip() == "1":
        return True
    print(
        f"Image {image_name} predates running apps as the SSH user, so its "
        "containers run as root. Rebuild the image to run as the SSH user."
    )
    return False


def _ssh_prefix(ssh_host, ssh_port, ssh_user):
    """Return the ``ssh`` invocation an operator can use to reach the server.

    If the user's SSH config has a short alias for the server (see
    :func:`_ssh_alias`), that is all the invocation needs. A user name with
    an ``@``, such as an email address, is passed with ``-l``, which reads
    better than ``user@example.org@host``.
    """
    key = str(get_server_pem_path())
    alias = _ssh_alias(ssh_host, ssh_port, ssh_user, key)
    if alias:
        return f"ssh {alias}"
    ssh_port_part = f"-p {ssh_port} " if ssh_port != 22 else ""
    if ssh_user and "@" in ssh_user:
        destination = f"-l {quote(ssh_user)} {quote(ssh_host)}"
    else:
        destination = quote(f"{ssh_user}@{ssh_host}" if ssh_user else ssh_host)
    return f"ssh {ssh_port_part}-i {quote(key)} {destination}"


def _ssh_alias(ssh_host, ssh_port, ssh_user, key):
    """Return the first label of ``ssh_host`` if it is an SSH alias for the server.

    For example, ``rr-pc02`` for ``rr-pc02.example.org``, if ``ssh -G
    rr-pc02`` gives the same host name, port and user, and ``key`` among its
    identity files. Otherwise None.
    """
    alias = ssh_host.split(".")[0]
    if alias == ssh_host or not alias or _is_ip_address(ssh_host):
        return None
    options = _ssh_config(alias)
    if options is None:
        return None

    def resolved(path):
        return os.path.realpath(os.path.expanduser(path))

    if (
        options.get("hostname") == [ssh_host]
        and options.get("port") == [str(ssh_port)]
        and options.get("user") == [ssh_user or getuser()]
        and resolved(key)
        in {resolved(path) for path in options.get("identityfile", [])}
    ):
        return alias
    return None


def _log_command(ssh_prefix, app):
    """Return the ssh command that follows an app's Compose logs."""
    return ssh_command(
        ssh_prefix,
        f"docker compose -f ~/dallinger/{app}/docker-compose.yml logs -f",
    )


def _public_dashboard_url(hostname):
    """Return a dashboard URL that does not embed credentials."""
    return f"https://{hostname}/dashboard"


def _record_deployment_infos(experiment_id, lines):
    """Persist operator notes to deploy_logs/ without secrets."""
    deploy_log_path = Path("deploy_logs") / f"{experiment_id}.txt"
    deploy_log_path.parent.mkdir(exist_ok=True)
    deploy_log_path.write_text("\n".join(lines) + "\n")


def _print_deployment_infos(lines, dashboard_password):
    """Print operator notes and the dashboard password."""
    for line in lines:
        print_bold(line)
    print_bold(f"Dashboard password: {dashboard_password}")


def _record_then_launch(
    executor, target, deployment_infos, dashboard_password, update, show_summary=True
):
    """Record the deployment, wait for the public URL, then launch the experiment.

    The record comes first so it exists even if the deploy stops here. A
    missing ``curl`` in the web image, or an app whose own ``/health`` does
    not answer 2xx, fails before the long public wait.
    Launching opens recruitment, so it only happens once participants can
    reach the public URL; if the bounded wait times out, nothing is launched.
    Returns the ``/launch`` response, or an empty dict in update mode.
    Without ``show_summary``, neither the notes nor the recruitment message
    are printed, unless launching fails and so the caller gets no result.
    """
    if show_summary:
        _print_deployment_infos(deployment_infos, dashboard_password)
    _record_deployment_infos(target.app, deployment_infos)
    if update:
        print("Not launching again: this is an update of a running experiment.")
        return {}
    try:
        check_internal_health(executor, target)
        wait_for_public_url(executor, target)
        print("Launching the experiment...")
        launch_data = launch_from_server(executor, target)
    except BaseException:
        if not show_summary:
            _print_deployment_infos(deployment_infos, dashboard_password)
        raise
    if show_summary:
        print(launch_data.get("recruitment_msg"))
    return launch_data


def _install_tunnel_token(executor, sftp, app, connector_token, tunnel_id):
    """Install the per-app connector token at mode 0600. Do not log the token.

    The tunnel id (not secret) is kept next to it, so a later deploy can tell
    this server's tunnel from a same-named one elsewhere.
    """
    executor.run(f"mkdir -p -m 700 ~/dallinger/{app}/secrets")
    sftp.putfo(
        BytesIO(f"{tunnel_id}\n".encode()),
        f"dallinger/{app}/secrets/cloudflare-tunnel-id",
    )
    sftp.putfo(
        BytesIO((connector_token + "\n").encode()),
        f"dallinger/{app}/secrets/cloudflare-tunnel-token",
    )
    executor.run(f"chmod 600 ~/dallinger/{app}/secrets/cloudflare-tunnel-token")


_CLOUDFLARE_TOKEN_KEYS = ("cloudflare_api_token", "cloudflare_keychain_service")


def _abort_cloudflare(exc):
    raise click.ClickException(f"Cloudflare error: {exc}") from exc


def check_deploy_credentials(server=None, ingress=None, config_options=None):
    """Check that a docker-ssh deploy can load the credentials it needs.

    ``docker-ssh deploy`` and ``sandbox`` load the token themselves before
    they contact the server. Tools that wrap them can call this earlier,
    before their own preparation, so a missing Cloudflare API token stops the
    deploy before anything changes. The server and ingress are resolved as
    the deploy resolves them, and the token is only loaded for Cloudflare
    ingress.

    Parameters
    ----------
    server : str, optional
        Configured server name, or its short hostname, as for ``--server``.
        If omitted and exactly one server is configured, that server is used.
        If omitted and several are configured, the token is only checked for
        an explicit Cloudflare ``ingress``, because the deploy has not chosen
        a server whose default ingress applies yet.
    ingress : str, optional
        ``"classic"`` or ``"cloudflare"``, as for ``--ingress``. Defaults to
        the server's ``default_ingress``.
    config_options : mapping or iterable of (key, value) pairs, optional
        The deploy's ``-c`` options. Only ``cloudflare_api_token`` and
        ``cloudflare_keychain_service`` (and their synonyms) are applied, and
        only while the token is loaded.

    Returns
    -------
    str or None
        The Cloudflare API token, or ``None`` if the deploy uses classic
        ingress or its ingress is not known yet.

    Raises
    ------
    click.UsageError
        If ``server`` is not a configured server, no server is configured,
        or ``ingress`` is unknown.
    click.ClickException
        If the deploy uses Cloudflare ingress and the token can't be loaded,
        or a ``file:`` token option can't be read.
    """
    hosts = tuple(CONFIGURED_HOSTS)
    if server is None and not hosts:
        raise click.UsageError(
            "No server configured. Use `dallinger docker-ssh servers add` to add one."
        )
    if server is None and len(hosts) > 1:
        # Without a server, only an explicit --ingress tells which ingress is used.
        server_info = {}
        if not ingress:
            return None
    else:
        try:
            server_info = _resolve_server_info(hosts[0] if server is None else server)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
    if _resolve_ingress(server_info, ingress) != INGRESS_CLOUDFLARE:
        return None
    config = get_config(load=True)
    token_options = {}
    for key, value in dict(config_options or ()).items():
        # Not canonical_key(): it warns about deprecated names, and the deploy
        # applies the same options again later.
        key = config.synonyms.get(key, key)
        if key in _CLOUDFLARE_TOKEN_KEYS:
            token_options[key] = value
    with ExitStack() as stack:
        try:
            stack.enter_context(config.override(token_options, cast_types=True))
        except OSError as exc:
            raise click.ClickException(
                f"Could not read {exc.filename}: {exc.strerror}"
            ) from exc
        try:
            return load_api_token(config)
        except CloudflareError as exc:
            _abort_cloudflare(exc)


def _apply_config_options(config, config_options):
    """Apply ``-c`` options to ``config``, expanding ``file:`` values.

    Returns the options keyed by their canonical config names.
    """
    config_options = {
        config.canonical_key(key): value
        for key, value in dict(config_options or ()).items()
    }
    try:
        config.extend(config_options, cast_types=True)
    except OSError as exc:
        raise click.ClickException(
            f"Could not read {exc.filename}: {exc.strerror}"
        ) from exc
    return config_options


def _manual_removal_commands(name):
    """Return shell commands that remove the files of an invalid app name by hand.

    There is no ``docker compose down``: Compose can strip such a name to the
    project of a live app (``myapp~`` becomes ``myapp``).
    """
    return [
        f"rm -rf ~/dallinger/{quote(name)} ~/dallinger/caddy.d/{quote(name)}",
        f"{SERVER_COMPOSE} exec -T httpserver caddy reload --config /etc/caddy/Caddyfile",
    ]


def ensure_root_domain_ready(server, update, new_app=None, delete_data_command=None):
    """Offer to destroy the server's classic apps before a root-domain deploy.

    Without a terminal, refuses with the destroy commands to run first. The
    teardown keeps each app's data, as ``destroy --keep-data`` does, so no
    experiment data is deleted before the image build and destroy asks
    nothing once the user agrees. If ``new_app``, the app being deployed, is
    one of them, the prompt says that the deploy replaces its database and
    Redis volume.

    ``delete_data_command`` is the command printed for deleting an app's kept
    data, with ``{app}`` standing for the app name; it defaults to
    ``dallinger docker-ssh destroy … --remove-data``. If an app's name is not
    a valid app name, nothing is destroyed and the error says how to remove
    that app by hand.
    """
    if update:
        return True

    server = resolve_server_name(server, CONFIGURED_HOSTS)
    executor = _executor_for_server(server)
    conflicts = _host_caddy_apps(executor)
    if not conflicts:
        return True

    joined = ", ".join(conflicts)
    invalid = [name for name in conflicts if not APP_NAME_PATTERN.fullmatch(name)]
    if invalid:
        commands = "\n".join(
            f"  {command}"
            for name in invalid
            for command in _manual_removal_commands(name)
        )
        raise click.ClickException(
            f"Can't destroy {', '.join(map(repr, invalid))} automatically: not a "
            f"valid app name, so nothing was destroyed. Remove "
            f"{'its' if len(invalid) == 1 else 'their'} files on {server} by "
            f"hand, for example with:\n{commands}\nThese commands don't stop "
            "any containers or delete any data. Then deploy again."
        )
    destroy_cmds = "\n".join(
        f"  dallinger docker-ssh destroy --app {name} --server {server} --keep-data"
        for name in conflicts
    )
    if not _stdin_is_tty():
        raise click.ClickException(
            f"Deploying to the root domain of {server} requires destroying its "
            f"classic-ingress experiments first: {joined}. Without a terminal they "
            "can't be destroyed automatically. Destroy them, then deploy again:\n"
            f"{destroy_cmds}"
        )
    print(
        f"{RED}Root domain deployments require terminating existing experiments.{END}\n"
        f"{RED}Found deployed experiments:{END} {joined}"
    )
    print(
        f"{RED}Please destroy those experiments before deploying to the root domain.{END}\n"
        "Suggested commands:\n"
        f"{destroy_cmds}"
    )

    kept = "Their data is kept"
    if new_app in conflicts:
        kept += f", but this deploy replaces the database and Redis volume of {new_app}"
    if not click.confirm(
        f"Destroy these experiments automatically before proceeding? {kept}.",
        default=False,
    ):
        raise click.Abort()

    for name in conflicts:
        print_bold(f"Destroying {name} on server {server}")
        destroy.callback(
            server=server,
            app=name,
            keep_data=True,
            delete_data_command=delete_data_command
            and delete_data_command.replace("{app}", name),
        )

    executor = _executor_for_server(server)
    remaining = _host_caddy_apps(executor)
    if remaining:
        raise click.ClickException(
            f"Some experiments are still present: {', '.join(remaining)}."
        )

    return True


def _ignore_docker_ssh_resource_warnings():
    """Suppress ResourceWarnings from docker-py's shell-out SSH transport.

    In shell-out mode (``use_ssh_client=True``), docker-py never tracks the
    connection pools it creates, so ``client.close()`` cannot reach the
    spawned ``ssh`` subprocesses or their sockets. They are only reclaimed
    at garbage collection, which emits ResourceWarnings. This is harmless
    for a short-lived CLI process, so we mute those specific warnings
    rather than patching docker-py internals.

    The filters must be installed process-wide (not via a scoped
    ``catch_warnings`` block) because the warnings fire at garbage
    collection, after any scoped context would have exited. They are
    installed before the Docker client is created so mid-command GC
    cannot print them.
    """
    warnings.filterwarnings(
        "ignore",
        category=ResourceWarning,
        message=r"subprocess \d+ is still running",
    )
    warnings.filterwarnings(
        "ignore",
        category=ResourceWarning,
        message=r"unclosed <docker\.transport\.sshconn\.SSHSocket",
    )
    warnings.filterwarnings(
        "ignore",
        category=ResourceWarning,
        message=r"unclosed file <_io\.FileIO name=\d+ mode='[rw]b' closefd=True>",
    )


def _image_usable_from_registry(docker_client, image_name):
    """Return whether image_name can be deployed straight from the registry.

    Pushes a local copy if the registry does not have the image yet. Returns
    False when the registry cannot be consulted, leaving the caller to build the
    image. Only the registry interaction is guarded here: wrapping the deploy
    itself would turn any deploy failure into a silent rebuild and retry.
    """
    import docker

    try:
        # Use the docker_client to inspect the image
        docker_client.images.get_registry_data(image_name)
    except docker.errors.ImageNotFound:
        pass
    except Exception as e:
        print(f"Error checking remote image: {e}")
        return False
    else:
        print(f"Image {image_name} found on remote registry")
        return True

    # The image is not on the registry. Check if it's available locally
    # and push it if it is. If images.push succeeds it means the image is available locally
    print(f"Image {image_name} not found on remote registry. Trying to push")
    try:
        raw_result = docker_client.images.push(image_name)
        # This is brittle, but it's an edge case not worth more effort
        push_failed = bool(json.loads(raw_result.split("\r\n")[-2]).get("error"))
    except Exception as e:
        print(f"Error pushing image {image_name}: {e}")
        return False
    if push_failed:
        # The image is not available, neither locally nor on the remote registry
        print(
            f"Could not find image {image_name} specified in experiment config as `docker_image_name`"
        )
        raise click.Abort
    print(f"Image {image_name} pushed to remote registry")
    return True


def _build_and_push_image(
    config, experiment_files, app_name, server, local_build, push_build
):
    """Return the experiment image to deploy, building and pushing it if needed.

    Reuses ``docker_image_name`` when the registry has it. Otherwise
    assembles the experiment and builds the image, on the server unless
    ``local_build`` is set, and pushes it for a local build or with
    ``push_build``.
    """
    import docker

    from dallinger.command_line.docker import push_image
    from dallinger.docker.tools import build_image, docker_tag_from_experiment_id

    image_name = config.get("docker_image_name", None)

    # If we build locally we have to push the image to the registry
    push_build = push_build or local_build

    # Save any current values from environment so we can restore them
    original_docker_host = os.environ.get("DOCKER_HOST")

    docker_client = None
    try:
        if not local_build:
            # Set DOCKER_HOST to point to the remote server via SSH
            server_info = _resolve_server_info(server)
            ssh_host, ssh_port = split_ssh_host_port(server_info["host"])
            ssh_user = server_info.get("user")
            ensure_remote_host_in_known_hosts(server_info["host"], ssh_user)
            os.environ["DOCKER_HOST"] = docker_host_uri(
                ssh_host, user=ssh_user, port=ssh_port
            )
            logging.getLogger(__name__).debug(
                "Using remote Docker host %s", os.environ["DOCKER_HOST"]
            )
            # Add server_pem to SSH agent so docker-py's SSH client can use it
            # (necessary because docker.from_env() does not accept PEM files directly).
            add_server_pem_to_ssh_agent()
        # docker-py leaks shell-out SSH resources; mute the GC warnings
        # before the client exists so they cannot fire mid-command.
        _ignore_docker_ssh_resource_warnings()
        # Avoid Paramiko by using the system ssh client
        docker_client = docker.from_env(use_ssh_client=True)

        if image_name and _image_usable_from_registry(docker_client, image_name):
            return image_name

        _, tmp_dir = setup_experiment(
            Output().log,
            exp_config=config.as_dict(),
            local_checks=False,
            app=app_name,
            experiment_files=experiment_files,
            quiet=True,
        )
        image_name = build_image(
            tmp_dir,
            config.get("docker_image_base_name"),
            out=Output(),
            image_tag=docker_tag_from_experiment_id(config.get("id")),
            quiet=True,
        )

        remote_build = not local_build
        if remote_build and not push_build:
            # If built remotely and not pushing, the image is only on the remote daemon.
            # We need to get its full name (repo:tag) for deployment.
            # The build_image function already returns the image name, so we use that.
            logging.getLogger(__name__).debug(
                "Image %s built remotely, skipping push to registry "
                "because --push-build was not selected.",
                image_name,
            )
            return image_name
        # If it's a local build, or if it's a remote build and push_build, then push.
        return push_image(image_name)
    finally:
        # Close client first so the SSH connection tears down cleanly
        if docker_client is not None:
            try:
                docker_client.close()
            except Exception:
                pass

        # Restore DOCKER_HOST
        if original_docker_host is None:
            os.environ.pop("DOCKER_HOST", None)
        else:
            os.environ["DOCKER_HOST"] = original_docker_host


def _report_ssh_failures(f):
    """Turn a failed SSH connection or login to the server into one ``Error:`` line.

    Other errors, including SSH errors after connecting, are raised unchanged.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            return f(*args, **kwargs)
        except Exception as exc:
            server_info = _configured_server_info(kwargs.get("server"))
            message = server_info and _ssh_failure_message(
                exc,
                server_info["host"],
                server_info.get("user"),
                docker_over_ssh=not kwargs.get("local_build"),
            )
            if not message:
                raise
            _stop_active_spinner()
            raise click.ClickException(message) from exc

    return wrapper


def _configured_server_info(server):
    """Return the configured details of ``server``, or None if it isn't configured."""
    try:
        return CONFIGURED_HOSTS[resolve_server_name(server, CONFIGURED_HOSTS)]
    except (KeyError, ValueError):
        return None


def _ssh_failure_message(exc, ssh_address, user, docker_over_ssh=False):
    """Explain ``exc`` if it means the server couldn't be reached or logged in to.

    Parameters
    ----------
    exc : Exception
        The error.
    ssh_address : str
        The server's ``host`` or ``host:port``.
    user : str or None
        The SSH user configured for the server.
    docker_over_ssh : bool
        Whether Docker was reaching the server over SSH, so that its failure to
        connect is an SSH problem.

    Returns
    -------
    str or None
        The explanation, or None for any other error.
    """
    import docker.errors

    host, port = split_ssh_host_port(ssh_address)
    address = host if port == 22 else f"{host}:{port}"

    def ssh_line(user, key=None):
        options = (f"-i {quote(str(key))} " if key else "") + (
            "" if port == 22 else f"-p {port} "
        )
        if user and "@" in user:
            return f"ssh {options}-l {user} {host}"
        return f"ssh {options}{user}@{host}" if user else f"ssh {options}{host}"

    def check(user):
        return (
            f"Check that `{ssh_line(user)}` works without asking for a "
            "password, using a key in ~/.ssh, your SSH agent or the server_pem "
            "setting."
        )

    prefix = "Error while fetching server API version: "
    if isinstance(exc, paramiko.AuthenticationException):
        login = f"Couldn't log in to {address} over SSH as {user or getuser()}."
        try:
            key = get_server_pem_path()
        except OSError:
            return f"{login} {check(user)}"
        # Dallinger's own SSH connections use only this key.
        return (
            f"{login} Check that `{ssh_line(user, key)}` works without asking for "
            "a password, with the key in the server_pem setting."
        )
    if (
        docker_over_ssh
        and isinstance(exc, docker.errors.DockerException)
        and str(exc).startswith(prefix)
    ):
        # Docker connects without a user name that contains "@" (see
        # docker_host_uri), so ssh picks the user as it would for this command.
        docker_user = None if user and "@" in user else user
        return (
            f"Couldn't reach Docker on {address} over SSH "
            f"({_root_cause(exc, prefix)}; see any message from ssh above). "
            f"{check(docker_user)}"
        )
    if not _raised_by_paramiko(exc):
        return None
    if isinstance(exc, socket.gaierror):
        reason = f"can't find a host called {host}"
    elif isinstance(exc, paramiko.ssh_exception.NoValidConnectionsError):
        reason = f"nothing accepted the connection on port {port}"
    elif isinstance(exc, TimeoutError):
        reason = "the connection timed out"
    elif isinstance(exc, paramiko.SSHException) and "protocol banner" in str(exc):
        reason = f"port {port} doesn't answer like an SSH server"
    else:
        return None
    return (
        f"Couldn't connect to {address} over SSH: {reason}. Check the server's "
        f"address and that it is running, then try `{ssh_line(user)}`."
    )


def _root_cause(exc, prefix=""):
    """Describe the innermost error behind ``exc``, such as "Broken pipe".

    Follows ``__cause__`` and ``__context__``, then an exception held in the
    arguments, as urllib3 does with ``ProtocolError("Connection aborted.",
    BrokenPipeError(...))``.
    """
    root, seen = exc, set()
    while id(root) not in seen:
        seen.add(id(root))
        nested = root.__cause__
        if nested is None and not root.__suppress_context__:
            nested = root.__context__
        if nested is None:
            nested = next(
                (a for a in reversed(root.args) if isinstance(a, BaseException)), None
            )
        if nested is None:
            break
        root = nested
    if root is exc:
        return str(exc).removeprefix(prefix)
    if getattr(root, "strerror", None) and not getattr(root, "filename", None):
        return root.strerror
    return str(root)


def _raised_by_paramiko(exc):
    """Return True if ``exc`` was raised inside Paramiko."""
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_globals.get("__name__", "").startswith("paramiko."):
            return True
        tb = tb.tb_next
    return False


def validate_update(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if kwargs["update"] and not kwargs.get("app_name"):
            raise click.UsageError(
                "Please specify the id of the running app to update with --app"
            )
        if kwargs["update"] and kwargs.get("archive_path"):
            raise click.UsageError(
                "Can't update an existing experiment with an archive: --archive and --update are mutually exclusive"
            )
        return f(*args, **kwargs)

    return wrapper


def get_dotenv_values(executor):
    dotenv_content = executor.run(
        "test -f ~/dallinger/.env.json && cat ~/dallinger/.env.json", raise_=False
    )
    if dotenv_content:
        return json.loads(dotenv_content)
    return {}


def set_dozzle_password(executor, sftp, new_password):
    import bcrypt

    dotenv_values = get_dotenv_values(executor)
    dotenv_values["DOZZLE_PASSWORD"] = new_password
    sftp.putfo(BytesIO(json.dumps(dotenv_values).encode()), "dallinger/.env.json")
    hashed = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )
    dozzle_users = {
        "users": {
            "dallinger": {
                "name": "Dallinger",
                "password": hashed,
                "email": "dallinger@example.com",
            }
        }
    }
    sftp.putfo(BytesIO(json.dumps(dozzle_users).encode()), "dallinger/dozzle-users.yml")
    dozzle_running = executor.run(
        "docker ps --filter name=^dozzle$ --format '{{.ID}}'",
        raise_=False,
    ).strip()
    if dozzle_running:
        executor.restart_dozzle()


def _start_server_services(executor):
    """Start the shared server services and wait until Postgres is healthy."""
    executor.run(f"{SERVER_COMPOSE} up -d")
    # A changed server compose file recreates the shared Postgres. Waiting
    # only on it keeps a crash-looping Caddy or Dozzle from blocking deploys.
    # coreutils `timeout` replaces `--wait-timeout`, which needs Compose 2.17.
    # The limit must exceed the worst case of docker-compose-server.yml.j2's
    # healthcheck: a 300 s start_period, then 15 retries that each cost the
    # 2 s interval plus the 5 s timeout when pg_isready hangs (405 s).
    limit = 420
    executor.run(
        f"timeout {limit} {SERVER_COMPOSE} up -d --wait postgresql"
        f" || {{ code=$?; [ $code -ne 124 ] || echo 'The shared PostgreSQL"
        f" was not healthy after {limit} s.' >&2; exit $code; }}"
    )


def ensure_postgres_schema_permissions(executor, experiment_id):
    # PostgreSQL 15+ no longer grants CREATE on schema public to all users.
    grant_schema_script = f'GRANT USAGE, CREATE ON SCHEMA public TO "{experiment_id}"'
    executor.run(
        f"{SERVER_COMPOSE} exec -T postgresql "
        f'psql -U dallinger -d "{experiment_id}" -c {quote(grant_schema_script)}'
    )


@docker_ssh.command("set-dozzle-password")
@option_server
@click.password_option()
def set_dozzle_password_cmd(server, password):
    server_info = _resolve_server_info(server)
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")

    executor = Executor(ssh_host, user=ssh_user)
    sftp = get_sftp(ssh_host, user=ssh_user)

    set_dozzle_password(executor, sftp, password)


@docker_ssh.command()
@option_app_name
@option_archive
@option_config
@option_dns_host
@option_server
@option_update
@option_local_build
@option_push_build
@option_ingress
@option_allow_private_ip
@option_show_summary
@option_deploy_delete_data_command
@validate_update
@_report_ssh_failures
def sandbox(**kwargs):  # pragma: no cover
    """Sandbox a dallinger experiment docker image to a server using ssh."""
    return _deploy_in_mode(mode="sandbox", **kwargs)


@docker_ssh.command()
@option_app_name
@option_archive
@option_config
@option_dns_host
@option_server
@option_update
@option_local_build
@option_push_build
@option_ingress
@option_allow_private_ip
@option_show_summary
@option_deploy_delete_data_command
@validate_update
@_report_ssh_failures
def deploy(**kwargs):  # pragma: no cover
    """Deploy a dallinger experiment docker image to a server using ssh."""
    return _deploy_in_mode(mode="live", **kwargs)


def _classic_tls_and_dns_host(config, ssh_host, dns_host):
    """Return the Caddy ``tls`` directive and the DNS host of a classic deploy.

    Raises ``click.ClickException`` if a server that needs a Let's Encrypt
    certificate has no valid ``contact_email_on_error``, and aborts if a
    server given as an IP address has no ``--dns-host``.
    """
    has_tls = not is_loopback_host(ssh_host)
    # We abuse the mturk contact_email_on_error to provide an email for let's encrypt certificate
    email_addr = config.get("contact_email_on_error")
    if has_tls:
        if "@" not in parseaddr(email_addr)[1]:
            raise click.ClickException(
                f"Email address absent or invalid. Value {email_addr} found. "
                "Run `dallinger email-test` to verify your configuration."
            )
    tls = "tls internal" if not has_tls else f"tls {email_addr}"

    # Check if server is an IP address
    try:
        socket.inet_aton(ssh_host)
        is_ip = True
    except socket.error:
        is_ip = False

    if not dns_host:
        if is_ip:
            print(
                f"""{RED}Error: When using an IP address as server ({ssh_host}), you must specify a DNS host.{END}
You have two options:
1. Use nip.io:
   --dns-host nip.io
   {RED}Using nip.io as part of the hostname might cause problems:{END}
   Some browsers might tell users this name is suspicious
2. Use a custom domain (recommended):
   Create a DNS A record pointing to {GREEN}{ssh_host}{END}
   and use option --dns-host to deploy the experiment.
   {BLUE}For instance to use the name experiment1.my-custom-domain.example.com
   you can pass options --app experiment1 --dns-host my-custom-domain.example.com{END}"""
            )
            raise click.Abort()
        else:
            # Not an IP address, use the server value as DNS host
            dns_host = ssh_host

    # Check if we're using nip.io (either provided or generated)
    if dns_host == "nip.io":
        dns_host = get_dns_host(ssh_host)
        print(f"""{RED}Using {dns_host} as hostname. This might cause problems:{END}
Some browsers might tell users this name is suspicious
You can override this by creating a DNS A record pointing to
{GREEN}{ssh_host}{END} and using option --dns-host to deploy the experiment.
{BLUE}For instance to use the name experiment1.my-custom-domain.example.com
you can pass options --app experiment1 --dns-host my-custom-domain.example.com{END}""")
    return tls, dns_host


def _deploy_in_mode(
    app_name,
    archive_path,
    config_options,
    dns_host,
    mode,
    server,
    update,
    local_build,
    push_build,
    ingress=None,
    allow_private_ip=False,
    show_summary=True,
    delete_data_command=None,
):
    """Check a docker-ssh deploy, build or reuse its image, then deploy it.

    Building the image can take minutes, so every check that does not need
    the image runs first. The root-domain cleanup, which can destroy apps,
    follows the other checks. Only the app-name check comes after it, since
    the cleanup can free that name; the Compose project check comes before
    it, since the cleanup keeps the data that a clashing name would share.
    """
    experiment_files = get_experiment_files(os.getcwd())
    server = resolve_server_name(server, CONFIGURED_HOSTS)
    # Existing apps already have their certificates, so updates skip the check.
    if not allow_private_ip and not update:
        _check_classic_ingress_reachable(server, ingress)
    config = get_config(load=True)
    config_options = _apply_config_options(config, config_options)

    run_pre_launch_checks(**locals())

    server_info = CONFIGURED_HOSTS[server]
    ssh_address = server_info["host"]
    ssh_host, ssh_port = split_ssh_host_port(ssh_address)
    ssh_user = server_info.get("user")

    experiment_uuid = str(uuid4())
    use_subdomain = should_use_subdomain(app_name, archive_path)
    if app_name:
        experiment_id = app_name
    elif archive_path:
        experiment_id = get_experiment_id_from_archive(archive_path)
    else:
        experiment_id = f"dlgr-{experiment_uuid[:8]}"
    if not APP_NAME_PATTERN.fullmatch(experiment_id):
        raise click.UsageError(f"Invalid docker-ssh app name {experiment_id!r}.")

    resolved_ingress = _resolve_ingress(server_info, ingress)
    if resolved_ingress == INGRESS_CLOUDFLARE:
        try:
            validate_app_dns_label(experiment_id)
        except CloudflareError as exc:
            _abort_cloudflare(exc)
        cloudflare_settings = _cloudflare_settings(config)
        try:
            api_token = load_api_token(config)
        except CloudflareError as exc:
            _abort_cloudflare(exc)
    else:
        cloudflare_settings = None
        tls, dns_host = _classic_tls_and_dns_host(config, ssh_host, dns_host)
        experiment_hostname = (
            f"{experiment_id}.{dns_host}" if use_subdomain else dns_host
        )
        _check_experiment_hostname_dns(ssh_host, experiment_hostname, allow_private_ip)

    slot_executor = Executor(ssh_address, user=ssh_user, app=experiment_id)
    _check_compose_project_free(slot_executor, experiment_id, update)
    if _root_domain_preflight_required(server, app_name, archive_path, ingress):
        ensure_root_domain_ready(
            server=server,
            update=update,
            new_app=experiment_id,
            delete_data_command=delete_data_command,
        )
    _check_app_slot(slot_executor, experiment_id, update, resolved_ingress)

    image_name = _build_and_push_image(
        config, experiment_files, app_name, server, local_build, push_build
    )
    # Read after the build, which sets a dashboard password if config has none.
    dashboard_user = config.get("dashboard_user", "admin")
    dashboard_password = config.get("dashboard_password", secrets.token_urlsafe(8))

    if cloudflare_settings is not None:
        return _deploy_cloudflare_in_mode(
            api_token=api_token,
            archive_path=archive_path,
            config=config,
            config_options=config_options,
            dashboard_password=dashboard_password,
            dashboard_user=dashboard_user,
            experiment_id=experiment_id,
            experiment_uuid=experiment_uuid,
            image_name=image_name,
            mode=mode,
            push_build=push_build,
            server=server,
            server_info=server_info,
            settings=cloudflare_settings,
            update=update,
            show_summary=show_summary,
        )

    app_identifier = app_name or experiment_id
    executor = Executor(ssh_address, user=ssh_user, app=app_identifier)
    executor.run("mkdir -p ~/dallinger/caddy.d")

    if not update:
        logging.getLogger(__name__).debug("Removing any pre-existing Redis volumes.")
        remove_redis_volumes(app_identifier, executor)

    sftp = get_sftp(ssh_address, user=ssh_user)
    dozzle_base = "/logs" if not use_subdomain else ""
    rendered_compose = DOCKER_COMPOSE_SERVER_TPL.render(dozzle_base=dozzle_base)
    sftp.putfo(BytesIO(rendered_compose.encode()), "dallinger/docker-compose.yml")
    caddy_template = CADDYFILE_SUBDOMAIN if use_subdomain else CADDYFILE_ROOT
    caddy_kwargs = {"host": dns_host, "tls": tls}
    if not use_subdomain:
        caddy_kwargs["backend"] = f"{app_identifier}_web:5000"
    sftp.putfo(
        BytesIO(caddy_template.format(**caddy_kwargs).encode()),
        "dallinger/Caddyfile",
    )

    dozzle_password = get_dotenv_values(executor).get(
        "DOZZLE_PASSWORD", dashboard_password
    )
    set_dozzle_password(executor, sftp, dozzle_password)

    print("Launching http, postgresql and dozzle servers.")
    _start_server_services(executor)

    if not update:
        print("Starting the experiment server...")
    else:
        print("Restarting the experiment server...")

    logs_url = (
        f"https://{dns_host}/logs" if not use_subdomain else f"https://logs.{dns_host}"
    )
    if show_summary:
        print_bold(
            f"To view the logs for this experiment go to {logs_url} (user = dallinger, password = {dozzle_password})"
        )
    app_secrets = _app_secrets(executor, experiment_id, update)
    postgresql_password = app_secrets["POSTGRES_PASSWORD"]
    cfg = _compose_environment(
        config,
        config_options,
        mode,
        experiment_uuid,
        image_name,
        app_secrets["FLASK_SECRET_KEY"],
    )
    public_origin = public_origin_for_hostname(experiment_hostname)
    previous_image = _upload_app_stack(
        sftp,
        executor,
        cfg,
        app=experiment_id,
        server=server,
        public_origin=public_origin,
        image_name=image_name,
        ingress=INGRESS_CLASSIC,
        secrets=app_secrets,
    )
    # Running "ls" in the `web` container blocks until `web`'s own dependencies
    # (redis and pgbouncer) are healthy. The shared Postgres belongs to another
    # compose project; the `up --wait` above already waited for it.
    executor.run(
        f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml run --rm web ls"
    )
    grant_roles_script = (
        f'grant all privileges on database "{experiment_id}" to "{experiment_id}"'
    )
    if not update:
        print("Cleaning up the database and its user...")
        executor.run(
            rf"""{SERVER_COMPOSE} exec -T postgresql psql -U dallinger -c 'DROP DATABASE IF EXISTS "{experiment_id}";'"""
        )
        executor.run(
            rf"""{SERVER_COMPOSE} exec -T postgresql psql -U dallinger -c 'DROP USER IF EXISTS "{experiment_id}"; '"""
        )
        print(f"Creating database {experiment_id}...")
        executor.run(
            rf"""{SERVER_COMPOSE} exec -T postgresql psql -U dallinger -c 'CREATE DATABASE "{experiment_id}"'"""
        )

        if archive_path is not None:
            print(f"Loading database data from {archive_path}...")
            with remote_postgres(server_info, experiment_id) as db_uri:
                engine = create_db_engine(db_uri)
                bootstrap_db_from_zip(archive_path, engine)
                with engine.connect() as conn:
                    conn.execute(grant_roles_script)
                    conn.execute(f'GRANT USAGE ON SCHEMA public TO "{experiment_id}"')
                    conn.execute(
                        f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA PUBLIC TO "{experiment_id}"'
                    )

    test_user_script = (
        rf"""SELECT FROM pg_catalog.pg_roles WHERE rolname = '{experiment_id}'"""
    )
    query_user_result = executor.run(
        f"{SERVER_COMPOSE} exec -T postgresql psql -U dallinger -c {quote(test_user_script)}",
        raise_=False,
    )
    if "0 rows" in query_user_result:
        # Create the user: it doesn't exist yet
        create_user_script = f"""CREATE USER "{experiment_id}" with encrypted password '{postgresql_password}'"""
        executor.run(
            f"{SERVER_COMPOSE} exec -T postgresql psql -U dallinger -c {quote(create_user_script)}"
        )
    else:
        # Change the password of the existing user
        change_password_script = f"""ALTER USER "{experiment_id}" WITH ENCRYPTED PASSWORD '{postgresql_password}'"""
        executor.run(
            f"{SERVER_COMPOSE} exec -T postgresql psql -U dallinger -c {quote(change_password_script)}"
        )

    executor.run(
        f"{SERVER_COMPOSE} exec -T postgresql psql -U dallinger -c {quote(grant_roles_script)}"
    )
    ensure_postgres_schema_permissions(executor, experiment_id)

    # Classic already restored any archive above. ``restore=False`` keeps
    # that work from running a second time.
    _bring_up_app_containers(
        executor,
        server_info,
        experiment_id,
        archive_path,
        update,
        restore=False,
    )
    _remove_replaced_image(executor, experiment_id, previous_image, image_name)

    if use_subdomain:
        # We give caddy the alias for the service. If we scale up the service container caddy will
        # send requests to all of them in a round robin fashion.
        caddy_conf = f"{experiment_hostname} {{\n    {tls}\n    reverse_proxy {experiment_id}_web:5000\n}}"
        sftp.putfo(
            BytesIO(caddy_conf.encode()),
            f"dallinger/caddy.d/{experiment_id}",
        )

    # Tell caddy we changed something in the configuration
    executor.reload_caddy()

    ssh_prefix = _ssh_prefix(ssh_host, ssh_port, ssh_user)
    launch_target = LaunchTarget(
        app=experiment_id,
        server=server,
        public_origin=public_origin,
        ingress=INGRESS_CLASSIC,
        ssh_prefix=ssh_prefix,
        verify=not is_loopback_host(ssh_host),
    )
    dashboard_link = _public_dashboard_url(experiment_hostname)
    log_command = _log_command(ssh_prefix, experiment_id)
    deployment_infos = []
    if push_build:
        deployment_infos.append(f"Deployed Docker image name: {image_name}")

    deployment_infos += [
        "To display the logs for this experiment you can run:",
        log_command,
        f"Or you can head to {logs_url} (user = dallinger)",
        f"You can now log in to the console at {dashboard_link} (user = {dashboard_user})",
    ]
    launch_data = _record_then_launch(
        executor,
        launch_target,
        deployment_infos,
        dashboard_password,
        update,
        show_summary,
    )
    return {
        "dashboard_user": dashboard_user,
        "dashboard_password": dashboard_password,
        "dashboard_link": dashboard_link,
        "log_command": log_command,
        "logs_url": logs_url,
        "logs_password": dozzle_password,
        "image_name": image_name,
        "app": experiment_id,
        "server": server,
        "ingress": INGRESS_CLASSIC,
        "public_origin": public_origin,
        "recruitment_msg": launch_data.get("recruitment_msg"),
    }


def _compose_environment(
    config, config_options, mode, experiment_uuid, image_name, flask_secret_key
):
    """Build the Compose environment map shared by classic and tunnel stacks."""
    from dallinger.docker.tools import docker_worker_processes

    cfg = config.as_dict(include_sensitive=True)
    for key in "aws_access_key_id", "aws_secret_access_key":
        cfg[key.upper()] = cfg.pop(key, None)
    cfg.update(
        {
            "FLASK_SECRET_KEY": flask_secret_key,
            "AWS_DEFAULT_REGION": config["aws_region"],
            "smtp_username": config.get("smtp_username"),
            "auto_recruit": config["auto_recruit"],
            "mode": mode,
            "CREATOR": f"{USER}@{HOSTNAME}",
            "DALLINGER_UID": experiment_uuid,
            "ADMIN_USER": "admin",
            "docker_image_name": image_name,
        }
    )
    for key, value in dict(config_options).items():
        cfg[config.canonical_key(key)] = value
    cfg["worker_processes"] = docker_worker_processes(config)
    # ``HOST`` is set by the template; the rest are secrets the app must not get.
    for key in "host", "database_url", "heroku_auth_token", "cloudflare_api_token":
        cfg.pop(key, None)
    if _idle_settings(cfg)[0] and _is_true(cfg.get("auto_recruit")):
        print(
            "Idle sleep stays off while auto_recruit is on, so the app can "
            "replace participants who drop out."
        )
    return cfg


def _deploy_cloudflare_in_mode(
    *,
    api_token,
    archive_path,
    config,
    config_options,
    dashboard_password,
    dashboard_user,
    experiment_id,
    experiment_uuid,
    image_name,
    mode,
    push_build,
    server,
    server_info,
    settings,
    update,
    show_summary=True,
):
    """Deploy an isolated Cloudflare-tunnel experiment on a docker-ssh host.

    ``settings`` are the account and zone from ``_cloudflare_settings``.
    The caller has already checked that the app slot is free (or exists,
    for ``--update``) and loaded ``api_token``.
    """
    print("Setting up the Cloudflare tunnel...")
    hostname = cloudflare_public_hostname(experiment_id, settings["dns_zone"])
    public_origin = public_origin_for_hostname(hostname)
    ssh_address = server_info["host"]
    ssh_host, ssh_port = split_ssh_host_port(ssh_address)
    ssh_user = server_info.get("user")
    executor = Executor(ssh_address, user=ssh_user, app=experiment_id)

    if not update:
        logging.getLogger(__name__).debug(
            "Removing any pre-existing Redis and Postgres volumes."
        )
        _remove_cloudflare_volumes(experiment_id, executor)
    app_secrets = _app_secrets(executor, experiment_id, update)

    # This server's own tunnel, recorded when its connector token was
    # installed (also after a deploy that failed later), or in the manifest.
    own_tunnel_id = (
        executor.run(
            f"cat ~/dallinger/{experiment_id}/secrets/cloudflare-tunnel-id",
            raise_=False,
        )
        or ""
    ).strip()
    if not own_tunnel_id and update:
        manifest = _load_remote_manifests(executor, [experiment_id]).get(experiment_id)
        own_tunnel_id = (manifest.cloudflare.get("tunnel_id") if manifest else "") or ""
    sftp = get_sftp(ssh_address, user=ssh_user)
    try:
        tunnel = ensure_experiment_tunnel(
            account_id=settings["account_id"],
            zone_id=settings["zone_id"],
            app=experiment_id,
            dns_zone=settings["dns_zone"],
            api_token=api_token,
            own_tunnel_id=own_tunnel_id or None,
        )
    except CloudflareError as exc:
        _abort_cloudflare(exc)

    try:
        _install_tunnel_token(
            executor,
            sftp,
            experiment_id,
            tunnel["connector_token"],
            tunnel["tunnel_id"],
        )
    except Exception:
        if tunnel["tunnel_id"] != own_tunnel_id:
            # Nothing on the server records this new tunnel, so no later
            # deploy or destroy could find it.
            print("Deleting the new Cloudflare tunnel, which could not be recorded.")
            delete_experiment_tunnel(
                account_id=settings["account_id"],
                zone_id=settings["zone_id"],
                app=experiment_id,
                dns_zone=settings["dns_zone"],
                api_token=api_token,
                own_tunnel_id=tunnel["tunnel_id"],
            )
        raise
    cfg = _compose_environment(
        config,
        config_options,
        mode,
        experiment_uuid,
        image_name,
        app_secrets["FLASK_SECRET_KEY"],
    )
    previous_image = _upload_app_stack(
        sftp,
        executor,
        cfg,
        app=experiment_id,
        server=server,
        public_origin=public_origin,
        image_name=image_name,
        ingress=INGRESS_CLOUDFLARE,
        secrets=app_secrets,
        cloudflare=public_resource_ids(tunnel),
    )

    if not update:
        print("Starting the experiment server...")
    else:
        print("Restarting the experiment server...")

    executor.run(
        f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml run --rm web ls"
    )
    if update:
        # Re-applies the password, so an app whose ``.env`` was lost or
        # recreated still matches its database.
        change_password_script = f"""ALTER USER "{experiment_id}" WITH ENCRYPTED PASSWORD '{app_secrets["POSTGRES_PASSWORD"]}'"""
        executor.run(
            f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml exec -T postgresql psql -U {quote(experiment_id)} -c {quote(change_password_script)}",
            raise_=False,
        )
    _bring_up_app_containers(
        executor,
        server_info,
        experiment_id,
        archive_path,
        update,
        restore=True,
    )
    _remove_replaced_image(executor, experiment_id, previous_image, image_name)

    ssh_prefix = _ssh_prefix(ssh_host, ssh_port, ssh_user)
    launch_target = LaunchTarget(
        app=experiment_id,
        server=server,
        public_origin=public_origin,
        ingress=INGRESS_CLOUDFLARE,
        ssh_prefix=ssh_prefix,
    )
    dashboard_link = _public_dashboard_url(hostname)
    log_command = _log_command(ssh_prefix, experiment_id)
    deployment_infos = []
    if push_build:
        deployment_infos.append(f"Deployed Docker image name: {image_name}")
    deployment_infos += [
        "To display the logs for this experiment you can run:",
        log_command,
        f"Public origin: {public_origin}",
        f"You can now log in to the console at {dashboard_link} (user = {dashboard_user})",
    ]
    launch_data = _record_then_launch(
        executor,
        launch_target,
        deployment_infos,
        dashboard_password,
        update,
        show_summary,
    )
    return {
        "dashboard_user": dashboard_user,
        "dashboard_password": dashboard_password,
        "dashboard_link": dashboard_link,
        "log_command": log_command,
        "image_name": image_name,
        "app": experiment_id,
        "server": server,
        "ingress": INGRESS_CLOUDFLARE,
        "public_origin": public_origin,
        "recruitment_msg": launch_data.get("recruitment_msg"),
        "tunnel_name": tunnel_name_for_app(experiment_id),
    }


def experiment_image_from_compose(compose_yml: str) -> str | None:
    """Return the image compose pins on the experiment ``web`` service."""
    if not compose_yml:
        return None
    match = re.search(r"(?m)^  web:\n(?:    .*\n)*?    image: (\S+)", compose_yml)
    if not match:
        return None
    return match.group(1).strip().strip("'\"") or None


def read_remote_experiment_image(executor, app: str) -> str | None:
    """Read the experiment image name from an app's remote compose file."""
    raw = executor.run(
        f"cat ~/dallinger/{app}/docker-compose.yml",
        raise_=False,
    )
    return experiment_image_from_compose(raw or "")


def apps_pinning_image(grep_paths: str, except_app: str) -> list[str]:
    """Return app names whose compose files pin an image, excluding ``except_app``."""
    apps = []
    for line in (grep_paths or "").splitlines():
        line = line.strip()
        if not line.endswith("docker-compose.yml"):
            continue
        app_name = PurePosixPath(line).parent.name
        if app_name and app_name != except_app:
            apps.append(app_name)
    return apps


def image_pinned_by_other_apps(executor, image_name: str, except_app: str) -> bool:
    """True if another app's compose file still pins this experiment image."""
    needle = f"    image: {image_name}"
    raw = executor.run(
        f"grep -xF -l {quote(needle)} $HOME/dallinger/*/docker-compose.yml",
        raise_=False,
    )
    return bool(apps_pinning_image(raw or "", except_app))


def remove_experiment_image(executor, image_name: str | None) -> None:
    """Remove a compose-pinned experiment image.

    ``docker rmi`` without ``--force`` leaves the image if a container still
    uses it.
    """
    if not image_name:
        return
    image = quote(image_name)
    result = executor.run(
        f"if docker rmi {image} >/dev/null 2>&1; then echo removed; "
        f"elif docker image inspect {image} >/dev/null 2>&1; then echo kept; fi",
        raise_=False,
    )
    result = (result or "").strip()
    if result == "removed":
        print(f"Removed experiment image {image_name}.")
    elif result == "kept":
        print(f"Kept experiment image {image_name} (still in use).")


def remove_unshared_experiment_image(
    executor, image_name: str | None, except_app: str
) -> None:
    """Remove an experiment image unless another app's compose still pins it."""
    if not image_name:
        return
    if image_pinned_by_other_apps(executor, image_name, except_app):
        print(f"Not removing image {image_name}: another app still pins it in compose")
        return
    remove_experiment_image(executor, image_name)


def get_experiment_id_from_archive(archive_path):
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open("experiment_id.md") as fh:
            return fh.read().decode("utf-8")


def remove_named_volume(volume_name, executor):
    """Remove a Docker volume if it exists."""
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        try:
            executor.run(f"docker volume rm '{volume_name}'")
        except ExecuteException:
            err = stdout.getvalue()
            if "no such volume" not in err.lower():
                raise ExecuteException(err)


def remove_redis_volumes(app_name, executor):
    remove_named_volume(f"{_compose_project(app_name)}_redis_data", executor)


def _remove_cloudflare_volumes(app, executor):
    """Remove a Cloudflare app's Redis and Postgres volumes, if they exist."""
    project = _compose_project(app)
    for volume in ("redis_data", "postgres_data"):
        remove_named_volume(f"{project}_{volume}", executor)


def get_apps(server):
    """Return discovered apps and their status on a configured server.

    Parameters
    ----------
    server : str
        Name of the configured server.
    Returns
    -------
    list of App
        App objects discovered on the server, each with ``name`` and ``state``.

    Raises
    ------
    ValueError
        If the server is not configured.
    """
    server_info = _resolve_server_info(server)
    executor = _build_executor(server_info)

    app_names = _discover_server_apps(executor)
    running_projects = _get_running_app_names(executor)
    manifests = _load_remote_manifests(executor, app_names)
    parked = _remote_hibernation_states(executor)

    apps = []
    for app_name in app_names:
        manifest = manifests.get(app_name)
        if app_name in parked:
            state = parked[app_name]
        elif app_name in running_projects:
            state = "running"
        else:
            state = "inactive"
        apps.append(
            App(
                name=app_name,
                state=state,
                ingress=manifest.ingress if manifest else "classic",
                public_origin=(manifest.public_origin or None) if manifest else None,
            )
        )
    return apps


@docker_ssh.command()
@option_server
def apps(server):
    """List dallinger apps running on the remote server."""
    try:
        apps = get_apps(server)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    if not apps:
        print("No apps found.")
        return []
    visible_apps = sorted(
        apps,
        key=lambda app: (app.state != "running", app.name),
    )

    rows = []
    for app in visible_apps:
        if app.state == "running":
            style = "green"
        elif app.state in {HIBERNATING, WAKING}:
            style = "yellow"
        else:
            style = "red"
        rows.append(
            [
                app.name,
                Text(app.state, style=style),
                app.ingress,
                app.public_origin or "",
            ]
        )
    print(render_rich_table(rows, headers=["app", "state", "ingress", "origin"]))
    return [app.name for app in visible_apps]


@docker_ssh.command()
@option_server
def stats(server):
    """Get resource usage stats from remote server."""
    executor = _executor_for_server(server)
    executor.run_and_echo("docker stats")


@docker_ssh.command()
@click.option(
    "--app",
    default=None,
    help=(
        "Name of the experiment app to export. If omitted and only one app exists "
        "on the server, it will be selected automatically"
    ),
)
@click.option(
    "--local",
    is_flag=True,
    flag_value=True,
    help="Only export data locally, skipping the Amazon S3 copy",
)
@click.option(
    "--no-scrub",
    is_flag=True,
    flag_value=True,
    help="Don't scrub PII (Personally Identifiable Information) - if not specified PII will be scrubbed",
)
@option_server
def export(app, local, no_scrub, server):
    """Export database to a local file."""
    try:
        server_info = _resolve_server_info(server)
    except ValueError as exc:
        raise click.UsageError(str(exc)) from exc
    if app is None:
        try:
            app = select_running_app(server)
        except ValueError as exc:
            raise click.UsageError(str(exc)) from exc
        click.echo(f"Exporting data from app '{app}'.")
    awaken_app(server, app, required=False)
    with remote_postgres(server_info, app) as db_uri:
        export_db_uri(
            app,
            db_uri=db_uri,
            local=local,
            scrub_pii=not no_scrub,
        )


def select_running_app(server):
    """Determine the currently deployed app on a server.

    Parameters
    ----------
    server : str
        Name of the configured server.
    Returns
    -------
    str
        The selected app name.

    Raises
    ------
    ValueError
        If zero or multiple apps are found running on the server.
    """
    apps = get_apps(server)
    running = [
        app.name for app in apps if app.state in {"running", HIBERNATING, WAKING}
    ]
    if len(running) == 1:
        return running[0]
    if len(running) > 1:
        listing = ", ".join(running)
        raise ValueError(
            f"Multiple running apps found on server '{server}': {listing}."
        )
    if len(running) == 0:
        raise ValueError(f"No running apps found on server '{server}'.")


def _get_running_app_names(executor):
    result = executor.run(
        "docker ps --format '{{.Label \"com.docker.compose.project\"}}'",
        raise_=False,
    )
    return {entry.strip() for entry in result.splitlines() if entry.strip()}


def _remote_hibernation_states(executor):
    """Return ``{app: "hibernating" | "waking"}`` from the apps' marker files."""
    listing = executor.run(
        f"ls -1 ~/dallinger/*/state/{HIBERNATING} ~/dallinger/*/state/{WAKING} "
        "2>/dev/null || true",
        raise_=False,
    )
    states = {}
    for line in (listing or "").splitlines():
        path = PurePosixPath(line.strip())
        if path.name in (HIBERNATING, WAKING) and path.parent.name == "state":
            states[path.parent.parent.name] = path.name
    return states


@contextmanager
def _forward_local_port(transport, remote_address):
    """Forward connections on a free localhost port to ``remote_address``.

    Each accepted connection gets its own ``direct-tcpip`` channel on
    ``transport``. Yields the local port; forwarding stops on exit.
    """
    listener = socket.create_server(("127.0.0.1", 0))
    listener.settimeout(0.5)
    stopping = threading.Event()

    def pipe(conn):
        try:
            chan = transport.open_channel(
                "direct-tcpip", remote_address, conn.getpeername()
            )
        except paramiko.SSHException as exc:
            logging.getLogger(__name__).warning(
                "Could not open SSH tunnel to %s:%s: %s", *remote_address, exc
            )
            conn.close()
            return
        with conn, chan:
            try:
                while not stopping.is_set():
                    readable, _, _ = select.select([conn, chan], [], [], 0.5)
                    for source, dest in ((conn, chan), (chan, conn)):
                        if source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            dest.sendall(data)
            except OSError:
                return  # Either side dropped the connection.

    def accept():
        while not stopping.is_set():
            try:
                conn, _ = listener.accept()
            except TimeoutError:
                continue
            threading.Thread(target=pipe, args=(conn,), daemon=True).start()

    acceptor = threading.Thread(target=accept, daemon=True)
    acceptor.start()
    try:
        yield listener.getsockname()[1]
    finally:
        stopping.set()
        # Closing the listener while accept() is blocked on it does not
        # stop new connections on all platforms, so wait for the loop first.
        acceptor.join()
        listener.close()


@contextmanager
def remote_postgres(server_info, app):
    """A context manager that opens an ssh tunnel to the remote host and
    returns a database URI to connect to it.

    The tunnel rides on the shared SSH connection, which stays open for
    other callers.
    """
    ssh_user = server_info.get("user")
    executor = Executor(server_info["host"], user=ssh_user, app=app)
    container, remote_ip, isolated = _resolve_remote_postgres(executor, app)
    if isolated:
        env = _inspect_container_env(executor, container)
        db_user = env.get("POSTGRES_USER") or app
        db_password = env.get("POSTGRES_PASSWORD") or ""
        db_name = env.get("POSTGRES_DB") or app
        if not db_password:
            raise ExecuteException(
                f"Could not read POSTGRES_PASSWORD from {container}."
            )
        uri_user = url_quote(db_user, safe="")
        uri_password = url_quote(db_password, safe="")
        uri_db = url_quote(db_name, safe="")
    else:
        uri_user = "dallinger"
        uri_password = "dallinger"
        uri_db = url_quote(app, safe="")
    with _forward_local_port(
        executor.client.get_transport(), (remote_ip, 5432)
    ) as local_port:
        yield (
            f"postgresql://{uri_user}:{uri_password}@127.0.0.1:{local_port}/{uri_db}"
        )


def _resolve_remote_postgres(executor, app):
    """Return (container, ip, isolated) for the app's Postgres, never a sibling app."""
    name = f"{app}_postgresql"
    ip = _inspect_container_ip(executor, name)
    if ip:
        return name, ip, True
    if _container_exists(executor, name):
        raise ExecuteException(
            f"Postgres container {name} exists but is not running. "
            "Awaken the app before export."
        )
    shared = "dallinger-postgresql-1"
    ip = _inspect_container_ip(executor, shared)
    if ip:
        return shared, ip, False
    raise ExecuteException(f"Could not find a Postgres container for app {app}.")


def _container_exists(executor, container):
    raw = executor.run(
        "docker inspect -f '{{.Id}}' " + quote(container),
        raise_=False,
    )
    # Errors go to stderr, which ``run`` does not return, so any output is an id.
    return bool((raw or "").strip())


def _inspect_container_ip(executor, container):
    raw = executor.run(
        "docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "
        + quote(container),
        raise_=False,
    )
    ip = (raw or "").strip().split()[0] if (raw or "").strip() else ""
    if not re.match(r"^\d{1,3}(?:\.\d{1,3}){3}$", ip):
        return ""
    return ip


def _inspect_container_env(executor, container):
    raw = executor.run(
        "docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "
        + quote(container),
        raise_=False,
    )
    env = {}
    for line in (raw or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            env[key] = value
    return env


def _app_data_link_target(executor, app):
    """Return ``(exists, symlink_target)`` for ``~/dallinger-data/<app>``.

    ``symlink_target`` is None unless the path is a symlink, dangling or not.
    """
    path = f"~/dallinger-data/{quote(app)}"
    out = executor.run(
        f'if [ -L {path} ]; then echo "symlink $(readlink {path})"; '
        f"elif [ -e {path} ]; then echo dir; fi",
        raise_=False,
    )
    out = (out or "").strip()
    if out.startswith("symlink"):
        return True, out[len("symlink") :].strip()
    return out == "dir", None


def _app_data_size(executor, app):
    """Return a human-readable size for the app's data folder, or None.

    ``du`` is capped at 15 seconds; a size from a ``du`` that hit unreadable
    files is reported as a lower bound.
    """
    out = executor.run(
        f'timeout 15 du -sh ~/dallinger-data/{quote(app)} 2>/dev/null; echo "rc=$?"',
        raise_=False,
    )
    lines = (out or "").strip().splitlines()
    if len(lines) < 2 or not lines[-1].startswith("rc="):
        return None
    size, rc = lines[0].split("\t")[0].strip(), lines[-1][3:]
    if not size or rc in ("124", "127"):
        return None
    return size if rc == "0" else f"at least {size}"


def _stdin_is_tty():
    """True if a user can answer a confirmation prompt."""
    return sys.stdin.isatty()


SHARED_PSQL_TIMEOUT = 30


def _shared_psql(*statements):
    """Return a command running SQL ``statements`` in the server's shared Postgres.

    Each statement gets its own ``-c``, so DROP DATABASE runs outside a
    transaction block.
    """
    args = " ".join(f"-c {quote(sql)}" for sql in statements)
    return (
        f"timeout {SHARED_PSQL_TIMEOUT} {SERVER_COMPOSE} exec -T postgresql "
        f"psql -U dallinger -v ON_ERROR_STOP=1 -tA {args}"
    )


def _shared_database(executor, app, required=True):
    """Return experiment data items for ``app``'s database and user in the shared Postgres.

    A Cloudflare app doesn't use the shared Postgres, but an earlier classic
    deploy of the same name may have left a database there. For such an app
    (``required=False``) a failed check prints a note instead of returning an
    ``unchecked`` item.
    """
    if app in SHARED_POSTGRES_DATABASES:
        return []
    status, out, err = executor.run_with_status(
        "[ -f ~/dallinger/docker-compose.yml ] || exit 0; "
        + _shared_psql(
            "SELECT (SELECT pg_size_pretty(pg_database_size(datname)) "
            f"FROM pg_database WHERE datname = '{app}'), "
            f"EXISTS (SELECT FROM pg_roles WHERE rolname = '{app}')"
        )
    )
    if status != 0:
        reason = _failure_reason(status, err, SHARED_PSQL_TIMEOUT)
        if required:
            if status == 124:
                reason += ", so try again"
            return [_unchecked(f"the database {app} in the shared Postgres", reason)]
        when = (
            "when the server is less busy"
            if status == 124
            else "after fixing the problem"
        )
        print(
            "Could not check whether the shared Postgres still has a database "
            f"{app} from an earlier classic deploy of this name ({reason}). "
            "The Cloudflare app's own database volume, if any, is listed "
            f"separately. If {app} was ever deployed with classic ingress, run "
            f"destroy with --remove-data again {when}."
        )
        return []
    size, _, has_user = (out or "").strip().partition("|")
    items = []
    if size:
        label = f"the database {app} ({size}) in the shared Postgres"
        items.append(("database", app, label))
    if has_user == "t":
        items.append(("user", app, f"the Postgres user {app}"))
    return items


def _failure_reason(status, err, timeout=None):
    """Describe why a remote command failed.

    For a command run under ``timeout`` seconds, exit status 124 means it
    timed out.
    """
    if timeout and status == 124:
        return f"timed out after {timeout} s; the server may be busy"
    return ((err or "").strip().splitlines()[-1:] or ["unknown error"])[0]


def _unchecked(what, reason):
    """Return an experiment data item for data whose existence is unknown."""
    return "unchecked", what, f"{what}, if any (could not check: {reason})"


def _own_database_size(executor, app):
    """Return the size of a Cloudflare app's database while its Postgres runs."""
    sql = f"SELECT pg_size_pretty(pg_database_size('{app}'))"
    status, out, _ = executor.run_with_status(
        f"timeout 20 docker exec {quote(app + '_postgresql')} "
        f"psql -U {quote(app)} -d {quote(app)} -tAc {quote(sql)}"
    )
    return (out or "").strip() if status == 0 else ""


def _experiment_data(executor, app, cloudflare=False):
    """List the experiment data ``app`` has on the server.

    Returns ``(kind, name, label)`` tuples for the app's database and user in
    the shared Postgres, its Docker volumes and its data folder. Each is
    checked on its own; one that can't be checked is an ``unchecked`` item,
    except the shared Postgres of a ``cloudflare`` app.
    """
    items = _shared_database(executor, app, required=not cloudflare)
    status, out, err = executor.run_with_status("docker volume ls -q")
    if status != 0:
        items.append(
            _unchecked(f"the Docker volumes of {app}", _failure_reason(status, err))
        )
        out = ""
    volumes = set(out.split())
    project = _compose_project(app)
    for volume, what in (("postgres_data", "database"), ("redis_data", "Redis")):
        volume = f"{project}_{volume}"
        if volume in volumes:
            size = _own_database_size(executor, app) if what == "database" else ""
            if size:
                label = f"the database {app} ({size}) in the volume {volume}"
            else:
                label = f"the {what} volume {volume}"
            items.append(("volume", volume, label))
    exists, link_target = _app_data_link_target(executor, app)
    if exists:
        path = f"~/dallinger-data/{app}"
        if link_target is not None:
            label = (
                f"the symlink {path} (only the link; its target {link_target} stays)"
            )
        else:
            size = _app_data_size(executor, app)
            label = f"the folder {path}" + (f" ({size})" if size else "")
        items.append(("folder", path, label))
    return items


def _print_data(heading, items):
    print(heading)
    for _, _, label in items:
        print(f"  - {label}")


def _remove_experiment_data(executor, app, items):
    """Delete the listed experiment data and return whether all of it is gone.

    Refuses unless Docker confirms that none of the app's containers run.
    """
    label = f"label=com.docker.compose.project={_compose_project(app)}"
    status, running, stderr = executor.run_with_status(
        f"docker ps -q --filter {quote(label)}"
    )
    if status != 0 or (running or "").strip():
        reason = (
            "could not check whether its containers are running"
            if status
            else "its containers are still running"
        )
        print(
            f"{RED}Not deleting the data of {app}: {reason}.{END} {(stderr or '').strip()}"
        )
        return False
    removed = True
    for kind, name, label in items:
        if kind == "folder":
            removed = _remove_app_data(executor, app) and removed
            continue
        if kind == "unchecked":
            removed = False
            print(f"{RED}Did not delete {label}.{END}")
            continue
        if kind == "database":
            command = _shared_psql(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{app}' AND pid <> pg_backend_pid()",
                f'DROP DATABASE IF EXISTS "{app}"',
            )
        elif kind == "user":
            command = _shared_psql(f'DROP USER IF EXISTS "{app}"')
        else:
            command = f"docker volume rm {quote(name)}"
        status, _, stderr = executor.run_with_status(command)
        if status == 0:
            print(f"Deleted {label}")
        else:
            removed = False
            timeout = SHARED_PSQL_TIMEOUT if kind in ("database", "user") else None
            reason = _failure_reason(status, stderr, timeout)
            print(f"{RED}Could not delete {label}.{END} {reason}")
    return removed


def _remove_app_data(executor, app):
    """Delete ``~/dallinger-data/<app>`` and return whether it is gone.

    The parent folder is usually root-owned, so the SSH user cannot unlink
    the app folder itself; a root container then deletes it. A symlink is
    unlinked; its target is kept.
    """
    path = f"~/dallinger-data/{app}"
    status, stdout, stderr = executor.run_with_status(
        f'app={quote(app)}; parent="$HOME/dallinger-data"; p="$parent/$app"; '
        'if [ -L "$p" ]; then kind="symlink $(readlink "$p")"; '
        'elif [ -e "$p" ]; then kind=dir; else echo absent; exit 0; fi; '
        'rm -rf "$p" 2>/dev/null || '
        'docker run --rm -v "$parent:/data" alpine:3.20 rm -rf "/data/$app"; '
        'if [ -e "$p" ] || [ -L "$p" ]; then echo failed; '
        'else echo "removed $kind"; fi'
    )
    result = (stdout or "").strip()
    if result == "removed dir":
        print(f"Deleted the folder {path}")
    elif result.startswith("removed symlink"):
        target = result[len("removed symlink") :].strip()
        print(f"Deleted the symlink {path}; its target {target} was kept.")
    elif result != "absent":
        print(f"{RED}Could not delete {path}.{END} {(stderr or '').strip()}")
        return False
    return True


@docker_ssh.command()
@click.option("--app", required=True, help="Name of the experiment app to destroy")
@click.option(
    "--remove-data",
    is_flag=True,
    help=(
        "Delete the experiment's data: its database, Redis volume and "
        "~/dallinger-data/<app>. Asks for confirmation unless --yes is given. "
        "Works after the app has been destroyed; if nothing is left, says so "
        "and exits successfully."
    ),
)
@click.option(
    "--keep-data",
    is_flag=True,
    help="Keep the experiment's data on the server and print how to delete it.",
)
@click.option(
    "--yes", is_flag=True, help="Don't ask before deleting data with --remove-data."
)
@click.option(
    "--delete-data-command",
    hidden=True,
    help=(
        "Command printed for deleting the kept data later, for tools that "
        "wrap this command."
    ),
)
@option_server
def destroy(
    server,
    app,
    remove_data=False,
    keep_data=False,
    yes=False,
    delete_data_command=None,
):
    """Tear down an experiment run on a server you control via ssh.

    Without --remove-data or --keep-data, asks whether to delete the
    experiment's data, or keeps it if there is no terminal to ask in. While
    another app on the server has the same Docker Compose project name (such
    as MyApp and myapp), destroy only runs if it keeps the data.
    """
    if not APP_NAME_PATTERN.fullmatch(app):
        raise click.UsageError(f"Invalid docker-ssh app name {app!r}.")
    if remove_data and keep_data:
        raise click.UsageError("Pass only one of --remove-data and --keep-data.")
    if not _stdin_is_tty():
        if remove_data and not yes:
            raise click.UsageError(
                "--remove-data needs confirmation; pass --yes in non-interactive "
                "sessions."
            )
        keep_data = not remove_data
    server_info = _resolve_server_info(server)
    ssh_address = server_info["host"]
    ssh_host, _ = split_ssh_host_port(ssh_address)
    ssh_user = server_info.get("user")
    executor = Executor(ssh_address, user=ssh_user, app=app)
    quoted_app = quote(app)

    caddy_config_exists = executor.run(
        f"test -f ~/dallinger/caddy.d/{quoted_app} && echo Yes", raise_=False
    )
    docker_compose_exists = executor.run(
        f"test -f ~/dallinger/{quoted_app}/docker-compose.yml && echo Yes",
        raise_=False,
    )
    # A Cloudflare deploy that failed after creating its tunnel leaves only
    # the connector token behind.
    tunnel_token_exists = executor.run(
        f"test -f ~/dallinger/{quoted_app}/secrets/cloudflare-tunnel-token && echo Yes",
        raise_=False,
    )
    deployed = caddy_config_exists or docker_compose_exists or tunnel_token_exists
    manifest = _load_remote_manifests(executor, [app]).get(app) if deployed else None
    if manifest:
        ingress = manifest.ingress
    elif tunnel_token_exists:
        ingress = INGRESS_CLOUDFLARE
    else:
        ingress = INGRESS_CLASSIC
    data = _experiment_data(executor, app, cloudflare=ingress == INGRESS_CLOUDFLARE)
    if not deployed and not data and remove_data:
        print(f"Nothing left to delete for {app} on {ssh_host}.")
        return
    if not deployed:
        print(f"App {app} is not deployed")
        if not data:
            print(f"No experiment data of {app} is left on {ssh_host}.")
            raise click.Abort()
    if data and not keep_data:
        siblings = _project_siblings(app, _discover_server_apps(executor))
        if siblings:
            others = ", ".join(siblings)
            keep = (
                f"Nothing was destroyed. To remove {app} and keep its data, run "
                "destroy with --keep-data; this also stops the containers of "
                f"{others}, which share the project, until {others} is "
                "deployed again with --update. "
                if deployed
                else ""
            )
            raise click.ClickException(
                f"The data of {app} can't be deleted while {others} exists on "
                f"{ssh_host}: they have the same Docker Compose project, "
                f"{_compose_project(app)}, so they share Docker volumes. {keep}"
                f"Once {others} is destroyed too, --remove-data can delete the "
                "data of each."
            )
    # Ask before teardown, so declining --remove-data leaves a live app untouched.
    if data and not keep_data and not (remove_data and yes):
        _print_data(f"Experiment data of {app} on {ssh_host}:", data)
        remove_data = click.confirm(
            "Delete this data? This cannot be undone."
            + ("" if remove_data else " Answer no to keep it."),
            default=False,
            abort=remove_data,
        )

    if deployed:
        _tear_down_app(
            executor,
            app,
            ssh_address,
            ssh_user,
            docker_compose_exists,
            manifest,
            ingress,
        )
    delete_again = (
        delete_data_command
        or f"dallinger docker-ssh destroy --app {app} --server {server} --remove-data"
    )
    if data and remove_data:
        if not _remove_experiment_data(executor, app, data):
            raise click.ClickException(
                f"Some data of {app} was not deleted. Fix the problem above "
                f"and run: {delete_again}"
            )
    elif data:
        _print_data(f"Kept the experiment data of {app} on {ssh_host}:", data)
        print(
            f"To delete it, run: {delete_again}\n"
            f"A new deploy of {app} without --update deletes its database and "
            f"volumes, but reuses ~/dallinger-data/{app}."
        )
        if not deployed:
            raise click.ClickException(
                f"App {app} is not deployed, so nothing was destroyed."
            )


def _tear_down_app(
    executor, app, ssh_address, ssh_user, has_compose, manifest, ingress
):
    """Stop and remove a deployed app, keeping its data volumes and folder."""
    ssh_host, _ = split_ssh_host_port(ssh_address)
    quoted_app = quote(app)

    experiment_image = None
    if has_compose:
        experiment_image = read_remote_experiment_image(executor, app)

    if ingress == INGRESS_CLOUDFLARE:
        if has_compose:
            _stop_cloudflare_connector(executor, app)
        own_tunnel_id = (
            executor.run(
                f"cat ~/dallinger/{quoted_app}/secrets/cloudflare-tunnel-id",
                raise_=False,
            )
            or ""
        ).strip() or (manifest.cloudflare.get("tunnel_id") if manifest else None)
        if not _destroy_cloudflare_resources(app, manifest, own_tunnel_id):
            print(
                f"The files for {app} are left on the server with its connector "
                "stopped. Fix the problem above and run destroy again."
            )
            raise click.Abort()
    else:
        caddyfile_content = executor.run("cat ~/dallinger/Caddyfile", raise_=False)
        uses_root_domain = f"reverse_proxy {app}_web:5000" in caddyfile_content
        dns_host = ssh_host
        executor.run(f"rm -f ~/dallinger/caddy.d/{quoted_app}")
        if uses_root_domain:
            config = get_config(load=True)
            email_addr = config.get("contact_email_on_error")
            has_tls = not is_loopback_host(ssh_host)
            tls_value = "tls internal" if not has_tls else f"tls {email_addr}"
            sftp = get_sftp(ssh_address, user=ssh_user)
            sftp.putfo(
                BytesIO(
                    CADDYFILE_SUBDOMAIN.format(host=dns_host, tls=tls_value).encode()
                ),
                "dallinger/Caddyfile",
            )
        executor.reload_caddy()
    if has_compose:
        status, _, stderr = executor.run_with_status(
            f"docker compose -f ~/dallinger/{quoted_app}/docker-compose.yml down"
        )
        if status != 0:
            print(
                f"{RED}Could not stop the containers of {app}:{END} "
                f"{(stderr or '').strip()}\nIts files are left on the server. "
                "Fix the problem and run destroy again."
            )
            raise click.Abort()
    remove_unshared_experiment_image(executor, experiment_image, except_app=app)
    executor.run(f"rm -rf ~/dallinger/{quoted_app}/")
    print(f"App {app} removed.")


def _stop_cloudflare_connector(executor, app):
    """Stop the tunnel connector so Cloudflare will accept tunnel deletion."""
    executor.run(
        f"docker compose -f ~/dallinger/{quote(app)}/docker-compose.yml stop cloudflared",
        raise_=False,
    )


def _destroy_cloudflare_resources(app, manifest=None, own_tunnel_id=None):
    """Delete the experiment CNAME and named tunnel. Return whether both are gone."""
    config = get_config(load=True)
    cloudflare = dict(manifest.cloudflare) if manifest else {}
    recorded = {
        key: cloudflare.get(key) for key in ("account_id", "zone_id", "dns_zone")
    }
    try:
        # Prefer the ids recorded at deploy time over this machine's config.
        settings = recorded
        if not all(recorded.values()):
            settings = _cloudflare_settings(config, dns_zone=recorded["dns_zone"])
            settings.update({key: value for key, value in recorded.items() if value})
        removed = delete_experiment_tunnel(
            account_id=settings["account_id"],
            zone_id=settings["zone_id"],
            app=app,
            dns_zone=settings["dns_zone"],
            api_token=load_api_token(config),
            own_tunnel_id=own_tunnel_id,
        )
    except (CloudflareError, click.UsageError) as exc:
        print(f"{RED}Cloudflare cleanup failed:{END} {exc}")
        return False
    deleted = []
    if removed.tunnel_name:
        deleted.append(f"Cloudflare tunnel {removed.tunnel_name}")
    if removed.hostname:
        deleted.append(f"DNS record {removed.hostname}")
    if deleted:
        print(f"Deleted {' and '.join(deleted)}.")
    if removed.skipped_tunnel_name:
        print(
            f"Left Cloudflare tunnel {removed.skipped_tunnel_name} in place "
            "because it belongs to another deploy."
        )
    if not removed:
        print(f"{RED}Cloudflare cleanup failed.{END} See the warnings above.")
    elif not deleted and not removed.skipped_tunnel_name:
        print(f"No Cloudflare tunnel or DNS record left to delete for {app}.")
    return bool(removed)


@docker_ssh.command()
@click.option("--app", required=True, help="Name of the experiment app to hibernate")
@option_server
def hibernate(server, app):
    """Stop expensive services for an app while keeping its front door awake."""
    _run_hibernation_action(server, app, "hibernate")


@docker_ssh.command()
@click.option("--app", required=True, help="Name of the experiment app to awaken")
@option_server
def awaken(server, app):
    """Start a hibernated app without re-launching recruitment."""
    _run_hibernation_action(server, app, "awaken")


def awaken_app(server, app, required=True):
    """Wake a docker-ssh app, waiting until Postgres and web are ready.

    Prints nothing if the app is already awake, so callers can use it as a
    routine check before touching the app's database.
    """
    return _run_hibernation_action(
        server, app, "awaken", required=required, report_awake=False
    )


def _run_hibernation_action(server, app, action, required=True, report_awake=True):
    if not APP_NAME_PATTERN.fullmatch(app):
        raise click.UsageError(f"Invalid docker-ssh app name {app!r}.")
    server_info = _resolve_server_info(server)
    ssh_address = server_info["host"]
    ssh_user = server_info.get("user")
    executor = Executor(ssh_address, user=ssh_user, app=app)
    compose = f"~/dallinger/{app}/docker-compose.yml"
    if not executor.run(f"test -f {compose} && echo Yes", raise_=False):
        print(f"App {app} is not deployed")
        if required:
            raise click.Abort()
        return False
    if action == "awaken" and app not in _remote_hibernation_states(executor):
        if report_awake:
            print(f"App {app} is awake")
        return True
    services = executor.run(
        f"docker compose -f {compose} config --services", raise_=False
    )
    if "controller" not in (services or "").split():
        print(
            f"{RED}App {app} was deployed before the front door existed; "
            f"redeploy it with --update to {action} it.{END}"
        )
        if required:
            raise click.Abort()
        return False
    try:
        result = executor.run(
            f"docker compose -f {compose} exec -T controller "
            f"python /app/hibernation.py {action}"
        )
    except ExecuteException:
        print(f"{RED}Could not {action} app {app}; see the error above.{END}")
        if required:
            raise
        return False
    print(result.strip() or f"App {app} {action} requested")
    return True


def _is_dsa_key(path):
    """Return whether the private key file at ``path`` holds a DSA key.

    Recognizes PEM (``BEGIN DSA PRIVATE KEY``) and OpenSSH formats. The
    public key in an OpenSSH file is not encrypted, so this also works for
    passphrase-protected keys.
    """
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return False
    if "-----BEGIN DSA PRIVATE KEY-----" in text:
        return True
    match = re.search(
        r"-----BEGIN OPENSSH PRIVATE KEY-----(.*?)-----END", text, re.DOTALL
    )
    if match is None:
        return False
    try:
        blob = base64.b64decode("".join(match.group(1).split()))
    except ValueError:
        return False
    return b"\x00\x00\x00\x07ssh-dss" in blob


class _PlainSpinner:
    """Stand-in for yaspin when stdout is not a terminal: no frames, one line per outcome."""

    def __init__(self, text=""):
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def start(self):
        pass

    def stop(self):
        pass

    def ok(self, text=""):
        print(" ".join(part for part in (text, self.text) if part), flush=True)

    fail = ok


_active_spinner = None


@contextmanager
def _spinner(text="", **kwargs):
    """Animate a yaspin spinner on a terminal; otherwise print only the outcome."""
    global _active_spinner
    spinner = yaspin(text=text, **kwargs) if sys.stdout.isatty() else None
    spinner = spinner or _PlainSpinner(text)
    previous, _active_spinner = _active_spinner, spinner
    try:
        with spinner:
            yield spinner
    finally:
        _active_spinner = previous
        sys.stdout.flush()


def _stop_active_spinner():
    """Clear a running spinner so that the next output starts on a clean line."""
    if _active_spinner is not None:
        _active_spinner.stop()


_ssh_clients = {}
_ssh_clients_lock = threading.Lock()


def _ssh_client_key(host, user=None):
    """Identify a login the same way however the host and user were spelled."""
    return (*split_ssh_host_port(host), user or getuser())


def _forget_ssh_client(host, user=None, client=None):
    """Close the shared connection to ``host`` so the next one logs in afresh.

    If ``client`` is given, it is closed, and dropped from the cache only if
    the cache still holds it rather than a newer connection.
    """
    key = _ssh_client_key(host, user)
    with _ssh_clients_lock:
        if client is None:
            client = _ssh_clients.pop(key, None)
        elif _ssh_clients.get(key) is client:
            del _ssh_clients[key]
    if client is not None:
        client.close()


def get_connected_ssh_client(host, user=None) -> paramiko.SSHClient:
    """Return a connected SSH client, reusing this process's open connection to ``host``.

    Callers share the client, so they should not close it unless they are
    finished with the server; a closed client is replaced on the next call.
    """
    key = _ssh_client_key(host, user)
    with _ssh_clients_lock:
        client = _ssh_clients.get(key)
        transport = client.get_transport() if client is not None else None
        if transport is not None and transport.is_active():
            return client
        if client is not None:
            client.close()
        client = _connect_ssh_client(host, user)
        _ssh_clients[key] = client
        return client


def _connect_ssh_client(host, user=None) -> paramiko.SSHClient:
    """Create and connect an SSH client with proper authentication.

    Args:
        host (str): The hostname or IP address to connect to
        user (str, optional): The username to use for authentication. Defaults to None.

    Returns:
        paramiko.SSHClient: A connected SSH client instance

    Note:
        The client is configured to automatically trust the remote host's key.
        This is a deliberate choice to simplify the connection process, as the server
        is expected to be under our control.
    """
    ssh_host, ssh_port = split_ssh_host_port(host)
    pem_path = get_server_pem_path()
    if _is_dsa_key(pem_path):
        raise click.ClickException(
            f"The server_pem key at {pem_path} is a DSA key, which Dallinger "
            "can no longer use. Replace it with an Ed25519, RSA, or ECDSA key: "
            "https://dallinger.readthedocs.io/en/latest/docker_support.html"
            "#replacing-a-dsa-key"
        )
    client = paramiko.SSHClient()

    known_hosts_path = os.path.expanduser("~/.ssh/known_hosts")
    try:
        client.load_host_keys(known_hosts_path)
    except IOError:
        # Paramiko may try to save host keys during connect(), which requires
        # the target file to already exist.
        os.makedirs(os.path.dirname(known_hosts_path), exist_ok=True)
        Path(known_hosts_path).touch(exist_ok=True)
        client.load_host_keys(known_hosts_path)

    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.load_system_host_keys()

    connect_kwargs = dict(
        hostname=ssh_host,
        port=ssh_port,
        username=user,
        key_filename=str(pem_path),
        allow_agent=False,  # don't use ssh-agent
        look_for_keys=False,  # don't scan ~/.ssh for keys
    )

    connecting_to = ssh_host if ssh_port == 22 else f"{ssh_host}:{ssh_port}"
    print(f"Connecting to {connecting_to}...", flush=True)
    with _spinner() as spinner:
        try:
            client.connect(**connect_kwargs)
            spinner.ok("Connected.")
        except paramiko.ssh_exception.BadHostKeyException as exc:
            # Host key changed — common when an EC2 instance is rebuilt.
            spinner.stop()
            click.echo(
                f"\nThe host key for '{exc.hostname}' has changed.\n"
                "This is expected if the server was recently rebuilt, "
                "but could indicate a security issue.\n"
                f"  Expected: {exc.expected_key.get_base64()}\n"
                f"  Got:      {exc.key.get_base64()}"
            )
            if not click.confirm(
                "Update the host key and continue connecting?",
                default=True,
            ):
                raise click.Abort()
            # Remove all stale entries (all key types) from known_hosts.
            # ssh-keygen -R handles plain and hashed hostnames alike.
            host_target = known_hosts_target(ssh_host, ssh_port)
            subprocess.run(
                ["ssh-keygen", "-R", host_target],
                capture_output=True,
            )
            # Recreate the client from the cleaned known_hosts so no
            # stale keys remain in memory for any key type.
            client = paramiko.SSHClient()
            try:
                client.load_host_keys(known_hosts_path)
            except IOError:
                pass
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            spinner.start()
            client.connect(**connect_kwargs)
            spinner.ok("Connected (host key updated).")
        except paramiko.AuthenticationException:
            spinner.fail("✖ Authentication failed")
            raise
        except Exception:
            spinner.fail("✖ Connection failed")
            raise
    # Deploys can sit idle for minutes (public URL wait, slow /launch);
    # keepalives stop NATs and firewalls from dropping the connection.
    client.get_transport().set_keepalive(30)

    try:
        client.save_host_keys(known_hosts_path)
    except IOError as exc:
        logging.getLogger(__name__).warning(
            "Could not persist SSH known host for %s: %s", connecting_to, exc
        )

    return client


def add_server_pem_to_ssh_agent():
    """Add server_pem to SSH agent so docker-py's SSH client can use it.

    Raises:
        click.ClickException: If ssh-add fails or is not available.
    """
    pem_path = get_server_pem_path()
    try:
        subprocess.run(
            ["ssh-add", str(pem_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            f"Failed to add SSH key to agent: {e.stderr}\n"
            f"Make sure ssh-agent is running and the key file exists at {pem_path}"
        ) from e
    except FileNotFoundError as e:
        raise FileNotFoundError(
            "ssh-add command not found. Please ensure SSH client tools are installed."
        ) from e


def ensure_remote_host_in_known_hosts(host, user=None):
    """Make sure the SSH host key is trusted locally before other clients connect.

    Raises
    ------
    click.ClickException
        If the server can't be reached or logged in to.
    """
    try:
        get_connected_ssh_client(host, user)
    except Exception as exc:
        message = _ssh_failure_message(exc, host, user)
        if message is None:
            raise
        raise click.ClickException(message) from exc


class Executor:
    """Execute remote commands using paramiko.

    All Executors for a server share one SSH connection. Closing ``client``
    closes it for every one of them; each reconnects on its next use.
    """

    def __init__(self, host, user=None, app=None):
        self.app = app
        self.host = host
        self.user = user
        # Connect now so that connection and login errors surface here.
        get_connected_ssh_client(host, user)

    @property
    def client(self):
        """The shared SSH client for this server, reconnected if it was closed."""
        return get_connected_ssh_client(self.host, self.user)

    def close(self):
        """Close the shared SSH connection for this server, without reconnecting."""
        _forget_ssh_client(self.host, self.user)

    def run(self, cmd, raise_=True):
        """Run the given command and block until it completes.
        If `raise` is True and the command fails, print the reason and raise an exception.
        """
        status, stdout, stderr = self.run_with_status(cmd)
        if raise_ and status != 0:
            _stop_active_spinner()
            print(f"Error: exit code was not 0 ({status})")
            print(stdout)
            print(stderr)
            compose_logs = self.print_docker_compose_logs(server=SERVER_COMPOSE in cmd)
            if _is_remote_disk_full_error(stdout, stderr, compose_logs):
                print(get_remote_disk_full_guidance(self.host))
                self.offer_safe_disk_cleanup()
            raise ExecuteException(
                f"An error occurred when running the following command on the remote server: \n{cmd}"
            )
        return stdout

    @staticmethod
    def _drain_channel(channel):
        """Drain stdout and stderr concurrently, then return (status, stdout, stderr).

        Draining both streams in separate threads prevents the SSH deadlock that
        occurs when recv_exit_status() is called while the remote command is blocked
        trying to write to a full stderr transport buffer.
        """
        stdout_chunks = []
        stderr_chunks = []

        def drain(recv_fn, buf):
            while True:
                chunk = recv_fn(65536)
                if not chunk:
                    break
                buf.append(chunk)

        t_out = threading.Thread(target=drain, args=(channel.recv, stdout_chunks))
        t_err = threading.Thread(
            target=drain, args=(channel.recv_stderr, stderr_chunks)
        )
        t_out.start()
        t_err.start()
        t_out.join()
        t_err.join()
        status = channel.recv_exit_status()
        return (
            status,
            b"".join(stdout_chunks).decode(errors="replace"),
            b"".join(stderr_chunks).decode(errors="replace"),
        )

    def run_with_status(self, cmd):
        """Run ``cmd`` and return ``(exit_status, stdout, stderr)`` without raising."""
        client = self.client
        try:
            channel = client.get_transport().open_session()
        except (paramiko.SSHException, EOFError):
            # A connection can die before its transport notices. A live one
            # refusing a channel (e.g. MaxSessions) must stay up for others.
            transport = client.get_transport()
            if transport is not None and transport.is_active():
                raise
            _forget_ssh_client(self.host, self.user, client)
            channel = self.client.get_transport().open_session()
        channel.exec_command(cmd)
        return self._drain_channel(channel)

    def print_docker_compose_logs(self, server=False):
        """Print and return the app's Compose logs, or the server stack's if ``server``."""
        if server:
            command = f"{SERVER_COMPOSE} logs --tail 200"
        elif self.app:
            command = f'docker compose -f "$HOME/dallinger/{self.app}/docker-compose.yml" logs'
        else:
            command = None
        if command:
            status, logs, _ = self.run_with_status(command)
            if status != 0:
                print("`docker compose` logs failed to run.")
                return ""
            else:
                print("*** BEGIN docker compose logs ***")
                print(logs)
                print("*** END docker compose logs ***\n")
                return logs
        return ""

    def offer_safe_disk_cleanup(self):
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            print("Non-interactive session detected; skipping automatic cleanup.")
            return
        if not click.confirm(
            "Run safe Docker cleanup now on the remote host? "
            "(unused images + stopped containers outside Compose projects)",
            default=False,
        ):
            return
        print("Running safe cleanup steps on the remote host:")
        for description, command in (
            ("Remove unused images", "docker image prune -af"),
            ("Remove stopped containers", CONTAINER_PRUNE),
        ):
            print(f"- {description}: {command}")
            status, stdout, stderr = self.run_with_status(command)
            if status != 0:
                print(f"Cleanup step failed with exit code {status}.")
                if stdout:
                    print(stdout)
                if stderr:
                    print(stderr)
                return
        print("Safe cleanup completed. Re-run your previous command.")

    def check_sudo(self):
        """Make sure the current user is authorized to invoke sudo without providing a password.
        If that is not the case print a message and raise click.Abort
        """
        if not self.run("sudo -n ls -l /", raise_=False):
            print(
                f"No passwordless sudo rights on {self.host}. Make sure your user can run sudo without a password.\n"
                "Run `sudo visudo` on the server and add this to the end of the file (replacing with the server username):\n"
                "<username> ALL=NOPASSWD: ALL"
            )
            raise click.Abort

    def reload_caddy(self):
        with _spinner(text="Reloading Caddy config file", color="green"):
            self.run(
                f"{SERVER_COMPOSE} exec -T httpserver "
                "caddy reload --config /etc/caddy/Caddyfile"
            )

    def restart_dozzle(self):
        with _spinner(text="Restarting Dozzle", color="green"):
            self.run(f"{SERVER_COMPOSE} restart dozzle")

    def run_and_echo(self, cmd):  # pragma: no cover
        """Execute the given command on the remote host and prints its output
        while it runs. Allows quitting by pressing the letter "q".
        Buffers lines to prevent flickering.

        Adapted from paramiko "interactive.py" demo.
        """
        from paramiko.util import u

        chan = self.client.get_transport().open_session()
        chan.exec_command(cmd)
        chan.settimeout(0.0)

        buffer = []
        while True:
            r, _, _ = select.select([chan, sys.stdin], [], [])
            if chan in r:
                try:
                    x = u(chan.recv(1024))
                    if len(x) == 0:
                        sys.stdout.write("\r\n*** EOF\r\n")
                        break
                    if "\n" in x:
                        sys.stdout.write("".join(buffer))
                        sys.stdout.write(x)
                        sys.stdout.flush()
                        buffer = []
                    else:
                        buffer.append(x)
                except socket.timeout:
                    pass
            if sys.stdin in r:
                x = sys.stdin.read(1)
                if len(x) == 0 or x in "qQ":
                    break


def _compose_project(app):
    """Return the Compose project name for ``app``, as Compose normalizes it.

    Compose labels the app's containers with this name.
    """
    return re.sub(r"[^a-z0-9_-]", "", app.lower())


def get_docker_compose_yml(
    config: Dict[str, str],
    experiment_id: str,
    experiment_image: str,
    ingress: str = INGRESS_CLASSIC,
    *,
    run_as_ssh_user: bool = True,
) -> str:
    """Render an app's docker-compose.yml. Secrets come from the app's ``.env``."""
    from dallinger.docker.tools import worker_cpu_shares

    docker_volumes = config.get("docker_volumes", "")
    worker_processes = int(config.get("worker_processes", 1))
    logger_filename = JSON_LOGFILE
    if logger_filename:
        new_volume = f"./{logger_filename}:/experiment/{logger_filename}"
        if docker_volumes:
            docker_volumes = f"{docker_volumes},{new_volume}"
        else:
            docker_volumes = new_volume
    config_str = {key: re.sub("\\$", "$$", str(value)) for key, value in config.items()}
    idle_enabled, idle_minutes = _idle_settings(config)
    return DOCKER_COMPOSE_EXP_TPL.render(
        ingress=ingress,
        experiment_id=experiment_id,
        experiment_image=experiment_image,
        config=config_str,
        docker_volumes=docker_volumes,
        worker_processes=worker_processes,
        worker_cpu_shares=worker_cpu_shares(worker_processes),
        idle_enabled=str(idle_enabled).lower(),
        idle_minutes=idle_minutes,
        controller_image=CONTROLLER_IMAGE,
        compose_project=_compose_project(experiment_id),
        run_as_ssh_user=run_as_ssh_user,
    )


def _write_app_env(sftp, executor, app, secrets):
    """Write the app's private ``.env``, which Compose reads for its secrets."""
    env_path = f"dallinger/{app}/.env"
    # Create the file private before any secret is written to it.
    executor.run(f"umask 077 && : > {env_path} && chmod 600 {env_path}")
    content = "".join(f"{key}={value}\n" for key, value in secrets.items())
    sftp.putfo(BytesIO(content.encode()), env_path)


def _bring_up_app_containers(
    executor,
    server_info,
    experiment_id,
    archive_path,
    update,
    *,
    restore,
):
    """Start Compose. An update of a hibernating app wakes it.

    Cloudflare sets ``restore`` so the archive is loaded before ``compose up``
    starts web. Classic restores earlier against the shared Postgres service.
    """
    if restore and archive_path is not None:
        _restore_experiment_archive(server_info, experiment_id, archive_path)
    state_dir = f"~/dallinger/{experiment_id}/state"
    markers = f"{state_dir}/{HIBERNATING} {state_dir}/{WAKING}"
    compose = f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml"
    steps = [f"for f in {markers}; do [ -e $f ] && echo was-hibernating; done; true"]
    if update:
        # Replace the controller first, so a hibernation it was running stops
        # before the markers go. Its bind-mounted script, and the front door's
        # Caddyfile, may also have changed without Compose noticing.
        steps.append(f"{compose} up -d --no-deps --force-recreate controller")
    # Touching the access log restarts the idle quiet period.
    steps += [
        f"{{ touch {state_dir}/access.log 2>/dev/null || true; }}",
        f"rm -f {markers}",
        f"{compose} up -d",
    ]
    if update:
        steps.append(f"{compose} up -d --no-deps --force-recreate frontdoor")
    output = executor.run(" && ".join(steps))
    if update and "was-hibernating" in (output or ""):
        print(f"App {experiment_id} was hibernating. The update woke it.")
    if archive_path is None and not update:
        executor.run(
            f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml "
            "exec -T web dallinger-housekeeper initdb"
        )


def _restore_experiment_archive(server_info, experiment_id, archive_path):
    """Load an export into the app database before web starts."""
    print(f"Loading database data from {archive_path}...")
    grant_roles_script = (
        f'grant all privileges on database "{experiment_id}" to "{experiment_id}"'
    )
    with remote_postgres(server_info, experiment_id) as db_uri:
        engine = create_db_engine(db_uri)
        bootstrap_db_from_zip(archive_path, engine)
        with engine.connect() as conn:
            conn.execute(grant_roles_script)
            conn.execute(f'GRANT USAGE ON SCHEMA public TO "{experiment_id}"')
            conn.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
                f'IN SCHEMA PUBLIC TO "{experiment_id}"'
            )


def _remote_bind_mount_dirs(docker_volumes, experiment_id):
    """Return quoted remote dirs to mkdir/chown for an app's bind mounts.

    Only the app data dir, the front-door state dir, and writable bind mounts
    strictly under ``$HOME`` qualify, so a mount such as ``/etc/ssl`` is
    never chowned.
    """
    dirs = ['"$HOME/dallinger-data/$app"', '"$HOME/dallinger/$app/state"']
    for spec in str(docker_volumes or "").split(","):
        parts = spec.strip().split(":")
        if len(parts) > 2 and "ro" in parts[2].split(","):
            continue
        host = parts[0].strip().replace("{{ experiment_id }}", experiment_id)
        for prefix in ("${HOME}/", "$HOME/", "~/"):
            rest = host[len(prefix) :].strip("/") if host.startswith(prefix) else ""
            if re.fullmatch(r"[A-Za-z0-9._/-]+", rest) and ".." not in rest.split("/"):
                snippet = f'"$HOME/{rest}"'
                if snippet not in dirs:
                    dirs.append(snippet)
    return dirs


def _write_experiment_compose_env(executor, experiment_id, docker_volumes=""):
    """Append UID/GID to the app's ``.env`` so its containers run as the SSH user.

    Older docker-ssh deploys left data dirs owned by root, so each dir from
    ``_remote_bind_mount_dirs`` is chowned recursively, falling back to a root
    ``alpine:3.20`` container. If that fails too, warn rather than abort: a
    fresh dir is still created as the SSH user.
    """
    app = quote(experiment_id)
    dirs = " ".join(_remote_bind_mount_dirs(docker_volumes, experiment_id))
    output = executor.run(
        "uid=$(id -u); gid=$(id -g); "
        "docker_gid=$(stat -c %g /var/run/docker.sock) || "
        "{ echo 'No Docker socket at /var/run/docker.sock.' >&2; exit 1; }; "
        f"app={app}; "
        'printf "UID=%s\\nGID=%s\\nDOCKER_GID=%s\\n" '
        '"$uid" "$gid" "$docker_gid" >> "$HOME/dallinger/$app/.env"; '
        f"for d in {dirs}; do "
        '  mkdir -p "$d"; '
        '  if chown -R "$uid:$gid" "$d" 2>/dev/null; then '
        "    :; "
        '  elif docker run --rm -v "$d:$d" '
        'alpine:3.20 chown -R "$uid:$gid" "$d"; then '
        "    :; "
        "  else "
        '    echo "Warning: could not chown $d for $app; '
        'root-owned files from older deploys may be unwritable."; '
        "  fi; "
        "done"
    )
    for line in (output or "").splitlines():
        if line.startswith("Warning:"):
            print(line)


def get_retrying_http_client():
    parameter_name = "method_whitelist"
    if hasattr(Retry.DEFAULT, "allowed_methods"):
        parameter_name = "allowed_methods"

    retry_strategy = Retry(
        total=30,
        backoff_factor=0.2,
        status_forcelist=[429, 500, 502, 503, 504],
        **{parameter_name: ["POST"]},
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    http = requests.Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)
    return http


def _ipv4_addresses(hostname):
    """Return the IPv4 addresses for hostname, or an empty list if lookup fails."""
    try:
        return gethostbyname_ex(hostname)[2]
    except (OSError, UnicodeError):
        # UnicodeError comes from the idna codec for malformed names,
        # for example a label longer than 63 characters.
        return []


def _check_experiment_hostname_dns(
    ssh_host, experiment_hostname, allow_private_ip=False
):
    """Abort unless the experiment hostname resolves to the SSH host IP.

    Parameters
    ----------
    ssh_host : str
        Host name or IP address used for SSH, without a port.
    experiment_hostname : str
        Public host name participants will use.
    allow_private_ip : bool
        If true, the SSH host's address may differ from the public one, so only
        require that ``experiment_hostname`` resolves.
    """
    ipaddr_experiment = next(iter(_ipv4_addresses(experiment_hostname)), None)
    if allow_private_ip and ipaddr_experiment:
        print(
            f"{experiment_hostname} resolves to {ipaddr_experiment}. Because of "
            "--allow-private-ip, this was not compared with the SSH host's address."
        )
        return
    ipaddr_server = next(iter(_ipv4_addresses(ssh_host)), None)
    if ipaddr_server and ipaddr_experiment == ipaddr_server:
        return

    if ipaddr_experiment:
        current_text = ipaddr_experiment
    else:
        current_text = "nothing (the name did not resolve)"

    checker_url = f"https://dnschecker.org/#A/{experiment_hostname}"
    print(f"{RED}DNS resolution error:{END}")
    if allow_private_ip or ipaddr_server:
        if allow_private_ip:
            expected = "the public IP that forwards ports 80 and 443 to the server"
        else:
            expected = ipaddr_server
        print(
            f"  The experiment hostname ({experiment_hostname}) should resolve to {expected}."
        )
        print(f"  It currently resolves to {current_text}.")
        print("  Check that --dns-host is correct.")
    else:
        print(
            f"  The server name ({ssh_host}) did not resolve to an IPv4 address, "
            f"so the experiment hostname ({experiment_hostname}) cannot be checked against it."
        )
        print(f"  The experiment hostname currently resolves to {current_text}.")
        print("  Check that the host configured for --server is correct.")
    print(
        f"  Confirm the A record globally at {checker_url} "
        "(green ticks mean it is resolving correctly)."
    )
    if ipaddr_server and ipaddr_experiment:
        print(
            "  If you recently reused this DNS name for a new server, caches may "
            "still point at the old IP. Dallinger Route 53 records use a 5-minute TTL, "
            "so wait about 5 minutes and try again, or use a different --dns-host."
        )
    elif not ipaddr_experiment:
        print(
            "  If you just provisioned the server, wait until DNS has propagated "
            "(up to about 5 minutes for Dallinger Route 53 records) and try again."
        )
    raise click.Abort()


def get_dns_host(ssh_host):
    """Return the nip.io name for ``ssh_host``'s IP address."""
    try:
        ip_addr = gethostbyname_ex(ssh_host)[2][0]
    except OSError as exc:
        raise click.ClickException(
            f"Can't find the IP address of {ssh_host} for --dns-host nip.io "
            f"({exc.strerror or exc}). Check the server's address."
        ) from exc
    return f"{ip_addr}.nip.io"


def _is_remote_disk_full_error(*outputs):
    output = "\n".join(str(chunk) for chunk in outputs if chunk).lower()
    return any(
        marker in output
        for marker in (
            "no space left on device",
            "diskfull",
            "disk full",
        )
    )


def get_remote_disk_full_guidance(host):
    guidance = [
        "",
        f"Remote Docker host '{host}' appears to be out of disk space.",
        "Safe cleanup steps (low-risk) are:",
        "  docker image prune -af",
        f"  {CONTAINER_PRUNE}",
        "",
        "Dallinger can run these safe steps for you automatically.",
        "We intentionally do not auto-prune volumes here, to avoid data loss.",
        "",
    ]
    return "\n".join(guidance)


class ExecuteException(Exception):
    pass


def get_sftp(host, user=None) -> paramiko.SFTPClient:
    client = get_connected_ssh_client(host, user)
    sftp = client.open_sftp()
    _, stdout, _ = client.exec_command('printf %s "$HOME"')
    remote_home = stdout.read().decode().strip()
    if remote_home:
        sftp.chdir(remote_home)
    return sftp


logging.getLogger("paramiko.transport").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
