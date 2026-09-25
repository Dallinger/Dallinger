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
from contextlib import contextmanager, redirect_stdout
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
from dallinger.deployment import handle_launch_data, setup_experiment
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
from .lib.cloudflare import public_hostname as cloudflare_public_hostname
from .utils import get_server_pem_path

# Hibernated apps keep stopped Compose containers that ``awaken`` restarts.
CONTAINER_PRUNE = "docker container prune -f --filter label!=com.docker.compose.project"


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

    with yaspin(text="Checking for Docker...", color="green") as sp:
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


def resolve_server_option(ctx, param, value):
    hosts = tuple(get_configured_hosts().keys())
    option_name = (
        f"--{param.name.replace('_', '-')}" if param is not None else "--server"
    )
    action = ctx.command.name if ctx is not None and ctx.command is not None else None

    if value is not None:
        if value not in hosts:
            choices = ", ".join(hosts) if hosts else "<none>"
            raise click.BadParameter(
                f"Unknown server '{value}'. Configured servers: {choices}",
                param=param,
            )
        return value

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
    help="Name of the remote server",
    type=click.Choice(tuple(CONFIGURED_HOSTS.keys())),
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
    left out of the URL, so the SSH client takes the user from
    ``~/.ssh/config``.
    """
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if user and "@" in user:
        print(
            f"SSH user {user!r} contains '@', so Docker connects without it. "
            f"Set `User {user}` for {host} in ~/.ssh/config."
        )
        user = None
    user_part = f"{user}@" if user else ""
    port_part = f":{port}" if port != 22 else ""
    return f"ssh://{user_part}{host}{port_part}"


def _resolve_server_info(server):
    try:
        return CONFIGURED_HOSTS[server]
    except KeyError as exc:
        raise ValueError(
            f"Unknown server '{server}', expected one of {list(CONFIGURED_HOSTS.keys())}."
        ) from exc


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
    server_info = CONFIGURED_HOSTS.get(server) or {}
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


def _cloudflare_settings(config, dns_zone=None):
    """Read non-secret Cloudflare account/zone settings from Dallinger config.

    ``--dns-host`` is a classic Caddy hostname and is never used as the
    Cloudflare DNS zone. ``dns_zone`` overrides config (destroy passes the
    zone recorded in the manifest).
    """
    account_id = str(config.get("cloudflare_account_id", "") or "").strip()
    zone_id = str(config.get("cloudflare_zone_id", "") or "").strip()
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


def _idle_settings(config_map):
    """Return idle hibernation flag and minutes from a compose/config mapping."""
    enabled = str(config_map.get("docker_ssh_idle_hibernate", False)).lower() in {
        "true",
        "1",
        "yes",
    }
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
    """
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
    env_path = f"dallinger/{app}/.env"
    env = "".join(f"{key}={value}\n" for key, value in secrets.items())
    # Create the file private before any secret is written to it.
    executor.run(f"umask 077 && : > {env_path} && chmod 600 {env_path}")
    sftp.putfo(BytesIO(env.encode()), env_path)
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


def _log_command(ssh_host, ssh_port, ssh_user, app):
    """Return the ssh command that follows an app's Compose logs."""
    ssh_port_part = f"-p {ssh_port} " if ssh_port != 22 else ""
    return (
        f"ssh {ssh_port_part}-i {get_server_pem_path()} "
        f"{(ssh_user + '@') if ssh_user else ''}{ssh_host} "
        f"docker compose -f '~/dallinger/{app}/docker-compose.yml' logs -f"
    )


def _public_dashboard_url(hostname):
    """Return a dashboard URL that does not embed credentials."""
    return f"https://{hostname}/dashboard"


def _record_deployment_infos(experiment_id, lines, dashboard_password):
    """Print operator notes, and persist them to deploy_logs/ without secrets."""
    for line in lines:
        print_bold(line)
    print_bold(f"Dashboard password: {dashboard_password}")
    deploy_log_path = Path("deploy_logs") / f"{experiment_id}.txt"
    deploy_log_path.parent.mkdir(exist_ok=True)
    deploy_log_path.write_text("\n".join(lines) + "\n")


def _install_tunnel_token(executor, sftp, app, connector_token, tunnel_id):
    """Install the per-app connector token at mode 0600. Do not log the token.

    The tunnel id (not secret) is kept next to it, so a later deploy can tell
    this server's tunnel from a same-named one elsewhere.
    """
    executor.run(f"mkdir -p -m 700 ~/dallinger/{app}/secrets")
    sftp.putfo(
        BytesIO((connector_token + "\n").encode()),
        f"dallinger/{app}/secrets/cloudflare-tunnel-token",
    )
    executor.run(f"chmod 600 ~/dallinger/{app}/secrets/cloudflare-tunnel-token")
    sftp.putfo(
        BytesIO(f"{tunnel_id}\n".encode()),
        f"dallinger/{app}/secrets/cloudflare-tunnel-id",
    )


def _abort_cloudflare(exc):
    print(f"{RED}Cloudflare error:{END} {exc}")
    raise click.Abort()


def ensure_root_domain_ready(server, update):
    if update:
        return True

    executor = _executor_for_server(server)
    conflicts = _discover_server_apps(executor)
    if not conflicts:
        return True

    joined = ", ".join(conflicts)
    print(
        f"{RED}Root domain deployments require terminating existing experiments.{END}\n"
        f"{RED}Found deployed experiments:{END} {joined}"
    )
    destroy_cmds = "\n".join(
        f"  dallinger docker-ssh destroy --app {name} --server {server}"
        for name in conflicts
    )
    print(
        f"{RED}Please destroy those experiments before deploying to the root domain.{END}\n"
        "Suggested commands:\n"
        f"{destroy_cmds}"
    )

    if not click.confirm(
        "Destroy these experiments automatically before proceeding?",
        default=False,
    ):
        raise click.Abort()

    for name in conflicts:
        print_bold(f"Destroying {name} on server {server}")
        destroy.callback(server=server, app=name)

    executor = _executor_for_server(server)
    remaining = _discover_server_apps(executor)
    if remaining:
        print(
            f"{RED}Some experiments are still present: {', '.join(remaining)}. Aborting.{END}"
        )
        raise click.Abort()

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


def build_and_push_image(f):
    """Decorator for click commands that depend on a pushed docker image.

    Commands using this decorator can rely on the image being present in
    the remote registry, and thus can use it to deploy to a remote server.

    Checks if the image is already present on the remote repository.
    If it's not builds the image and pushes it.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):  # pragma: no cover
        files = get_experiment_files(os.getcwd())

        import docker

        from dallinger.command_line.docker import push_image
        from dallinger.docker.tools import build_image, docker_tag_from_experiment_id

        config = get_config(load=True)
        image_name = config.get("docker_image_name", None)
        local_build = kwargs.get("local_build", False)

        # If we build locally we have to push the image to the registry
        push_build = kwargs.get("push_build", False) or local_build

        preflight_root_clean = False
        if _root_domain_preflight_required(
            kwargs["server"],
            kwargs.get("app_name"),
            kwargs.get("archive_path"),
            kwargs.get("ingress"),
        ):
            preflight_root_clean = ensure_root_domain_ready(
                server=kwargs["server"], update=kwargs.get("update", False)
            )
        kwargs["preflight_root_clean"] = preflight_root_clean

        # Save any current values from environment so we can restore them
        original_docker_host = os.environ.get("DOCKER_HOST")

        docker_client = None
        try:
            if not local_build:
                # Set DOCKER_HOST to point to the remote server via SSH
                server_info = CONFIGURED_HOSTS[kwargs["server"]]
                ssh_host, ssh_port = split_ssh_host_port(server_info["host"])
                ssh_user = server_info.get("user")
                ensure_remote_host_in_known_hosts(server_info["host"], ssh_user)
                os.environ["DOCKER_HOST"] = docker_host_uri(
                    ssh_host, user=ssh_user, port=ssh_port
                )
                print(
                    f"Attempting to build image on remote host: {os.environ['DOCKER_HOST']}"
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
                return f(*args, **dict(kwargs, image_name=image_name))

            app_name = kwargs.get("app_name", None)
            _, tmp_dir = setup_experiment(
                Output().log,
                exp_config=config.as_dict(),
                local_checks=False,
                app=app_name,
                experiment_files=files,
            )
            image_name = build_image(
                tmp_dir,
                config.get("docker_image_base_name"),
                out=Output(),
                image_tag=docker_tag_from_experiment_id(config.get("id")),
            )

            remote_build = not local_build
            if remote_build and not push_build:
                # If built remotely and not pushing, the image is only on the remote daemon.
                # We need to get its full name (repo:tag) for deployment.
                # The build_image function already returns the image name, so we use that.
                print(
                    f"Image {image_name} built remotely, skipping push to registry because --push-build was not selected."
                )
            else:
                # If it's a local build, or if it's a remote build and push_build, then push.
                image_name = push_image(image_name)

            return f(*args, **dict(kwargs, image_name=image_name))
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

    return wrapper


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


def ensure_postgres_schema_permissions(executor, experiment_id):
    # PostgreSQL 15+ no longer grants CREATE on schema public to all users.
    grant_schema_script = f'GRANT USAGE, CREATE ON SCHEMA public TO "{experiment_id}"'
    executor.run(
        "docker compose -f ~/dallinger/docker-compose.yml exec -T postgresql "
        f'psql -U dallinger -d "{experiment_id}" -c {quote(grant_schema_script)}'
    )


@docker_ssh.command("set-dozzle-password")
@option_server
@click.password_option()
def set_dozzle_password_cmd(server, password):
    server_info = CONFIGURED_HOSTS[server]
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
@validate_update
@build_and_push_image
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
@validate_update
@build_and_push_image
def deploy(**kwargs):  # pragma: no cover
    """Deploy a dallinger experiment docker image to a server using ssh."""
    return _deploy_in_mode(mode="live", **kwargs)


def _deploy_in_mode(
    app_name,
    archive_path,
    config_options,
    dns_host,
    image_name,
    mode,
    server,
    update,
    local_build,  # noqa
    push_build,
    preflight_root_clean,
    ingress=None,
):
    config = get_config(load=True)

    run_pre_launch_checks(**locals())

    server_info = CONFIGURED_HOSTS[server]
    ssh_address = server_info["host"]
    ssh_host, ssh_port = split_ssh_host_port(ssh_address)
    ssh_user = server_info.get("user")
    dashboard_user = config.get("dashboard_user", "admin")
    dashboard_password = config.get("dashboard_password", secrets.token_urlsafe(8))

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

    app_identifier = app_name or experiment_id
    if _resolve_ingress(server_info, ingress) == INGRESS_CLOUDFLARE:
        return _deploy_cloudflare_in_mode(
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
            update=update,
        )

    # We deleted this because synchronizing configs between local and remote can cause problems especially when using
    # different credential managers
    # copy_docker_config(ssh_host, ssh_user)
    HAS_TLS = not is_loopback_host(ssh_host)
    # We abuse the mturk contact_email_on_error to provide an email for let's encrypt certificate
    email_addr = config.get("contact_email_on_error")
    if HAS_TLS:
        if "@" not in parseaddr(email_addr)[1]:
            print(f"Email address absent or invalid. Value {email_addr} found")
            print("Run `dallinger email-test` to verify your configuration")
            raise click.Abort
    tls = "tls internal" if not HAS_TLS else f"tls {email_addr}"

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
    experiment_hostname = f"{experiment_id}.{dns_host}" if use_subdomain else dns_host

    _check_experiment_hostname_dns(ssh_host, experiment_hostname)

    executor = Executor(ssh_address, user=ssh_user, app=app_identifier)
    executor.run("mkdir -p ~/dallinger/caddy.d")

    if not use_subdomain and not preflight_root_clean:
        conflicts = _discover_server_apps(executor)
        if conflicts:
            joined = ", ".join(conflicts)
            print(
                f"{RED}Root domain deployments require terminating existing experiments.{END}\n"
                f"{RED}Found deployed experiments:{END} {joined}"
            )
            raise click.Abort()

    _check_app_slot(executor, app_identifier, update, INGRESS_CLASSIC)
    if not update:
        print("Removing any pre-existing Redis volumes.")
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
    executor.run("docker compose -f ~/dallinger/docker-compose.yml up -d")

    if not update:
        print("Starting experiment.")
    else:
        print("Restarting experiment.")

    logs_url = (
        f"https://{dns_host}/logs" if not use_subdomain else f"https://logs.{dns_host}"
    )
    print_bold(
        f"To view the logs for this experiment go to {logs_url} (user = dallinger, password = {dozzle_password})"
    )
    cfg = _compose_environment(
        config, config_options, mode, experiment_uuid, image_name
    )
    postgresql_password = (
        update and _existing_app_secret(executor, experiment_id, "POSTGRES_PASSWORD")
    ) or token_urlsafe(16)
    public_origin = public_origin_for_hostname(experiment_hostname)
    _upload_app_stack(
        sftp,
        executor,
        cfg,
        app=experiment_id,
        server=server,
        public_origin=public_origin,
        image_name=image_name,
        ingress=INGRESS_CLASSIC,
        secrets={"POSTGRES_PASSWORD": postgresql_password},
    )
    # We invoke the "ls" command in the context of the `web` container.
    # `docker compose` will honour `web`'s dependencies and block
    # until postgresql is ready. This way we can be sure we can start creating the database.
    executor.run(
        f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml run --rm web ls"
    )
    grant_roles_script = (
        f'grant all privileges on database "{experiment_id}" to "{experiment_id}"'
    )
    if not update:
        print("Cleaning up db/user")
        executor.run(
            rf"""docker compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c 'DROP DATABASE IF EXISTS "{experiment_id}";'"""
        )
        executor.run(
            rf"""docker compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c 'DROP USER IF EXISTS "{experiment_id}"; '"""
        )
        print(f"Creating database {experiment_id}")
        executor.run(
            rf"""docker compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c 'CREATE DATABASE "{experiment_id}"'"""
        )

        if archive_path is not None:
            print(f"Loading database data from {archive_path}")
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
        f"docker compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c {quote(test_user_script)}",
        raise_=False,
    )
    if "0 rows" in query_user_result:
        # Create the user: it doesn't exist yet
        create_user_script = f"""CREATE USER "{experiment_id}" with encrypted password '{postgresql_password}'"""
        executor.run(
            f"docker compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c {quote(create_user_script)}"
        )
    else:
        # Change the password of the existing user
        change_password_script = f"""ALTER USER "{experiment_id}" WITH ENCRYPTED PASSWORD '{postgresql_password}'"""
        executor.run(
            f"docker compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c {quote(change_password_script)}"
        )

    executor.run(
        f"docker compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c {quote(grant_roles_script)}"
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

    if update:
        print("Skipping experiment launch logic because we are in update mode.")
    else:
        print("Launching experiment")
        launch_data = handle_launch_data(
            f"https://{experiment_hostname}/launch",
            print,
            dns_host=dns_host,
            dozzle_password=dozzle_password,
            context="ssh",
            verify=HAS_TLS,
        )
        print(launch_data.get("recruitment_msg"))

    dashboard_link = _public_dashboard_url(experiment_hostname)
    log_command = _log_command(ssh_host, ssh_port, ssh_user, experiment_id)
    deployment_infos = []
    if push_build:
        deployment_infos.append(f"Deployed Docker image name: {image_name}")

    deployment_infos += [
        "To display the logs for this experiment you can run:",
        log_command,
        f"Or you can head to {logs_url} (user = dallinger)",
        f"You can now log in to the console at {dashboard_link} (user = {dashboard_user})",
    ]
    _record_deployment_infos(experiment_id, deployment_infos, dashboard_password)
    return {
        "dashboard_user": dashboard_user,
        "dashboard_password": dashboard_password,
        "dashboard_link": dashboard_link,
        "log_command": log_command,
        "app": experiment_id,
        "server": server,
        "ingress": INGRESS_CLASSIC,
        "public_origin": public_origin,
    }


def _compose_environment(config, config_options, mode, experiment_uuid, image_name):
    """Build the Compose environment map shared by classic and tunnel stacks."""
    cfg = config.as_dict(include_sensitive=True)
    for key in "aws_access_key_id", "aws_secret_access_key":
        cfg[key.upper()] = cfg.pop(key, None)
    cfg.update(
        {
            "FLASK_SECRET_KEY": token_urlsafe(16),
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
    cfg.update(config_options)
    # ``HOST`` is set by the template; the rest are secrets the app must not get.
    for key in "host", "database_url", "heroku_auth_token", "cloudflare_api_token":
        cfg.pop(key, None)
    return cfg


def _deploy_cloudflare_in_mode(
    *,
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
    update,
):
    """Deploy an isolated Cloudflare-tunnel experiment on a docker-ssh host."""
    try:
        validate_app_dns_label(experiment_id)
    except CloudflareError as exc:
        _abort_cloudflare(exc)

    settings = _cloudflare_settings(config)
    hostname = cloudflare_public_hostname(experiment_id, settings["dns_zone"])
    public_origin = public_origin_for_hostname(hostname)
    ssh_address = server_info["host"]
    ssh_host, ssh_port = split_ssh_host_port(ssh_address)
    ssh_user = server_info.get("user")
    executor = Executor(ssh_address, user=ssh_user, app=experiment_id)

    _check_app_slot(executor, experiment_id, update, INGRESS_CLOUDFLARE)
    if not update:
        print("Removing any pre-existing Redis and Postgres volumes.")
        remove_named_volume(f"{experiment_id}_redis_data", executor)
        remove_named_volume(f"{experiment_id}_postgres_data", executor)
    postgresql_password = (
        update and _existing_app_secret(executor, experiment_id, "POSTGRES_PASSWORD")
    ) or token_urlsafe(16)

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
    try:
        api_token = load_api_token(config)
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

    sftp = get_sftp(ssh_address, user=ssh_user)
    _install_tunnel_token(
        executor, sftp, experiment_id, tunnel["connector_token"], tunnel["tunnel_id"]
    )
    cfg = _compose_environment(
        config, config_options, mode, experiment_uuid, image_name
    )
    _upload_app_stack(
        sftp,
        executor,
        cfg,
        app=experiment_id,
        server=server,
        public_origin=public_origin,
        image_name=image_name,
        ingress=INGRESS_CLOUDFLARE,
        secrets={"POSTGRES_PASSWORD": postgresql_password},
        cloudflare=public_resource_ids(tunnel),
    )

    if not update:
        print("Starting experiment.")
    else:
        print("Restarting experiment.")

    executor.run(
        f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml run --rm web ls"
    )
    if update:
        # Re-applies the password, so an app whose ``.env`` was lost or
        # recreated still matches its database.
        change_password_script = f"""ALTER USER "{experiment_id}" WITH ENCRYPTED PASSWORD '{postgresql_password}'"""
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

    if update:
        print("Skipping experiment launch logic because we are in update mode.")
    else:
        print("Launching experiment")
        launch_data = handle_launch_data(
            f"{public_origin}/launch",
            print,
            dns_host=None,
            context="ssh",
        )
        print(launch_data.get("recruitment_msg"))

    dashboard_link = _public_dashboard_url(hostname)
    log_command = _log_command(ssh_host, ssh_port, ssh_user, experiment_id)
    deployment_infos = []
    if push_build:
        deployment_infos.append(f"Deployed Docker image name: {image_name}")
    deployment_infos += [
        "To display the logs for this experiment you can run:",
        log_command,
        f"Public origin: {public_origin}",
        f"You can now log in to the console at {dashboard_link} (user = {dashboard_user})",
    ]
    _record_deployment_infos(experiment_id, deployment_infos, dashboard_password)
    return {
        "dashboard_user": dashboard_user,
        "dashboard_password": dashboard_password,
        "dashboard_link": dashboard_link,
        "log_command": log_command,
        "app": experiment_id,
        "server": server,
        "ingress": INGRESS_CLOUDFLARE,
        "public_origin": public_origin,
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
    print(f"Removing experiment image {image_name}")
    executor.run(f"docker rmi {quote(image_name)}", raise_=False)


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
    remove_named_volume(f"{app_name}_redis_data", executor)


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
def remote_postgres(server_info, app):
    """A context manager that opens an ssh tunnel to the remote host and
    returns a database URI to connect to it.
    """
    from sshtunnel import SSHTunnelForwarder

    tunnel = None
    try:
        ssh_address = server_info["host"]
        ssh_host, ssh_port = split_ssh_host_port(ssh_address)
        ssh_user = server_info.get("user")
        executor = Executor(ssh_address, user=ssh_user, app=app)
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
        pem_path = get_server_pem_path()
        tunnel = SSHTunnelForwarder(
            (ssh_host, ssh_port),
            ssh_username=ssh_user,
            ssh_pkey=str(pem_path),
            remote_bind_address=(remote_ip, 5432),
        )
        tunnel.start()
        yield (
            f"postgresql://{uri_user}:{uri_password}"
            f"@localhost:{tunnel.local_bind_port}/{uri_db}"
        )
    finally:
        if tunnel is not None:
            tunnel.stop()


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


@docker_ssh.command()
@click.option("--app", required=True, help="Name of the experiment app to destroy")
@option_server
def destroy(server, app):
    """Tear down an experiment run on a server you control via ssh."""
    server_info = CONFIGURED_HOSTS[server]
    ssh_address = server_info["host"]
    ssh_host, _ = split_ssh_host_port(ssh_address)
    ssh_user = server_info.get("user")
    executor = Executor(ssh_address, user=ssh_user, app=app)

    caddy_config_exists = executor.run(
        f"test -f ~/dallinger/caddy.d/{app} && echo Yes", raise_=False
    )
    docker_compose_exists = executor.run(
        f"test -f ~/dallinger/{app}/docker-compose.yml && echo Yes", raise_=False
    )
    # A Cloudflare deploy that failed after creating its tunnel leaves only
    # the connector token behind.
    tunnel_token_exists = executor.run(
        f"test -f ~/dallinger/{app}/secrets/cloudflare-tunnel-token && echo Yes",
        raise_=False,
    )
    if not (caddy_config_exists or docker_compose_exists or tunnel_token_exists):
        print(f"App {app} is not deployed")
        raise click.Abort()

    manifest = _load_remote_manifests(executor, [app]).get(app)
    if manifest:
        ingress = manifest.ingress
    elif tunnel_token_exists:
        ingress = INGRESS_CLOUDFLARE
    else:
        ingress = INGRESS_CLASSIC

    experiment_image = None
    if docker_compose_exists:
        experiment_image = read_remote_experiment_image(executor, app)

    if ingress == INGRESS_CLOUDFLARE:
        if docker_compose_exists:
            _stop_cloudflare_connector(executor, app)
        own_tunnel_id = (
            executor.run(
                f"cat ~/dallinger/{app}/secrets/cloudflare-tunnel-id", raise_=False
            )
            or ""
        ).strip() or (manifest.cloudflare.get("tunnel_id") if manifest else None)
        if not _destroy_cloudflare_resources(app, manifest, own_tunnel_id):
            print(
                f"The files for {app} are left on the server with its connector "
                "stopped. Fix the problem above and run destroy again."
            )
            raise click.Abort()
        executor.run(
            f"docker compose -f ~/dallinger/{app}/docker-compose.yml down -v",
            raise_=False,
        )
    else:
        caddyfile_content = executor.run("cat ~/dallinger/Caddyfile", raise_=False)
        uses_root_domain = f"reverse_proxy {app}_web:5000" in caddyfile_content
        dns_host = ssh_host
        executor.run(f"rm -f ~/dallinger/caddy.d/{app}")
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
        executor.run(
            f"docker compose -f ~/dallinger/{app}/docker-compose.yml down",
            raise_=False,
        )

    remove_unshared_experiment_image(executor, experiment_image, except_app=app)
    executor.run(f"rm -rf ~/dallinger/{app}/")
    print(f"App {app} removed")


def _stop_cloudflare_connector(executor, app):
    """Stop the tunnel connector so Cloudflare will accept tunnel deletion."""
    executor.run(
        f"docker compose -f ~/dallinger/{app}/docker-compose.yml stop cloudflared",
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
    if not removed:
        print(f"{RED}Cloudflare cleanup failed.{END} See the warnings above.")
    return removed


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
    awaken_app(server, app)


def awaken_app(server, app, required=True):
    """Wake a docker-ssh app, waiting until Postgres and web are ready."""
    return _run_hibernation_action(server, app, "awaken", required=required)


def _run_hibernation_action(server, app, action, required=True):
    if not APP_NAME_PATTERN.fullmatch(app):
        raise click.UsageError(f"Invalid docker-ssh app name {app!r}.")
    server_info = CONFIGURED_HOSTS[server]
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


def get_connected_ssh_client(host, user=None) -> paramiko.SSHClient:
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
    print(f"Connecting to {connecting_to}")
    with yaspin() as spinner:
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
        except ValueError as ex:
            if "q must be exactly" in str(ex):
                raise ValueError(
                    f"The PEM key file at {pem_path} is not compatible with this EC2 instance.\n"
                    "Make sure you're using the correct EC2 key pair file that matches this instance.\n"
                    "Check your 'server_pem' configuration or use the correct key file."
                )
            else:
                raise
        except Exception:
            spinner.fail("✖ Connection failed")
            raise

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
    """Make sure the SSH host key is trusted locally before other clients connect."""
    client = get_connected_ssh_client(host, user)
    client.close()


class Executor:
    """Execute remote commands using paramiko"""

    def __init__(self, host, user=None, app=None):
        self.app = app
        self.client = get_connected_ssh_client(host, user)
        self.host = host

    def run(self, cmd, raise_=True):
        """Run the given command and block until it completes.
        If `raise` is True and the command fails, print the reason and raise an exception.
        """
        status, stdout, stderr = self._run_with_status(cmd)
        if raise_ and status != 0:
            print(f"Error: exit code was not 0 ({status})")
            print(stdout)
            print(stderr)
            compose_logs = self.print_docker_compose_logs()
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
            b"".join(stdout_chunks).decode(),
            b"".join(stderr_chunks).decode(),
        )

    def _run_with_status(self, cmd):
        channel = self.client.get_transport().open_session()
        channel.exec_command(cmd)
        return self._drain_channel(channel)

    def print_docker_compose_logs(self):
        if self.app:
            channel = self.client.get_transport().open_session()
            channel.exec_command(
                f'docker compose -f "$HOME/dallinger/{self.app}/docker-compose.yml" logs'
            )
            status, logs, _ = self._drain_channel(channel)
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
            status, stdout, stderr = self._run_with_status(command)
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
        with yaspin(text="Reloading Caddy config file", color="green"):
            self.run(
                "docker compose -f ~/dallinger/docker-compose.yml exec -T httpserver "
                "caddy reload --config /etc/caddy/Caddyfile"
            )

    def restart_dozzle(self):
        with yaspin(text="Restarting Dozzle", color="green"):
            self.run("docker compose -f ~/dallinger/docker-compose.yml restart dozzle")

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


def get_docker_compose_yml(
    config: Dict[str, str],
    experiment_id: str,
    experiment_image: str,
    ingress: str = INGRESS_CLASSIC,
    run_as_ssh_user: bool = True,
) -> str:
    """Render an app's docker-compose.yml. Secrets come from the app's ``.env``."""
    docker_volumes = config.get("docker_volumes", "")
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
        idle_enabled=str(idle_enabled).lower(),
        idle_minutes=idle_minutes,
        # Compose's own project-name normalization, which its labels use.
        compose_project=re.sub(r"[^a-z0-9_-]", "", experiment_id.lower()),
        run_as_ssh_user=run_as_ssh_user,
    )


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
        f"touch {state_dir}/access.log 2>/dev/null; rm -f {markers}",
        f"{compose} up -d",
    ]
    if update:
        steps.append(f"{compose} up -d --no-deps --force-recreate frontdoor")
    output = executor.run(" && ".join(steps))
    if update and "was-hibernating" in (output or ""):
        print(f"App {experiment_id} was hibernating. The update woke it.")
    if archive_path is None and not update:
        print(f"Experiment {experiment_id} started.")
        print("Initializing database...")
        executor.run(
            f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml "
            "exec -T web dallinger-housekeeper initdb"
        )
        print("Database initialized.")


def _restore_experiment_archive(server_info, experiment_id, archive_path):
    """Load an export into the app database before web starts."""
    print(f"Loading database data from {archive_path}")
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
    executor.run(
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


def _first_ipv4(hostname):
    """Return the first IPv4 address for hostname, or None if lookup fails."""
    try:
        return gethostbyname_ex(hostname)[2][0]
    except (OSError, UnicodeError):
        # UnicodeError comes from the idna codec for malformed names,
        # for example a label longer than 63 characters.
        return None


def _check_experiment_hostname_dns(ssh_host, experiment_hostname):
    """Abort unless the experiment hostname resolves to the SSH host IP."""
    ipaddr_server = _first_ipv4(ssh_host)
    ipaddr_experiment = _first_ipv4(experiment_hostname)
    if ipaddr_server and ipaddr_experiment == ipaddr_server:
        return

    if ipaddr_experiment:
        current_text = ipaddr_experiment
    else:
        current_text = "nothing (the name did not resolve)"

    checker_url = f"https://dnschecker.org/#A/{experiment_hostname}"
    print(f"{RED}DNS resolution error:{END}")
    if ipaddr_server:
        print(
            f"  The experiment hostname ({experiment_hostname}) should resolve to {ipaddr_server}."
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
    ip_addr = gethostbyname_ex(ssh_host)[2][0]
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
