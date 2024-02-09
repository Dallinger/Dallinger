import hashlib
import io
import json
import logging
import os
import re
import secrets
import select
import socket
import sys
import zipfile
from contextlib import contextmanager, redirect_stdout
from email.utils import parseaddr
from functools import wraps
from getpass import getuser
from io import BytesIO
from pathlib import Path
from secrets import token_urlsafe
from shlex import quote
from socket import gethostbyname_ex, gethostname
from subprocess import CalledProcessError
from typing import Dict
from uuid import uuid4

import click
import requests
from jinja2 import Template
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from yaspin import yaspin

from dallinger.command_line.config import get_configured_hosts, remove_host, store_host
from dallinger.command_line.utils import Output
from dallinger.config import get_config
from dallinger.data import bootstrap_db_from_zip, export_db_uri
from dallinger.db import create_db_engine
from dallinger.deployment import handle_launch_data, setup_experiment
from dallinger.utils import abspath_from_egg, check_output

# A couple of constants to colour console output
RED = "\033[31m"
END = "\033[0m"
GREEN = "\033[32m"
BLUE = "\033[34m"


# Find an identifier for the current user to use as CREATOR of the experiment
HOSTNAME = gethostname()
try:
    USER = getuser()
except KeyError:
    USER = "user"

DOCKER_COMPOSE_SERVER = abspath_from_egg(
    "dallinger", "dallinger/docker/ssh_templates/docker-compose-server.yml"
).read_bytes()

DOCKER_COMPOSE_EXP_TPL = Template(
    abspath_from_egg(
        "dallinger", "dallinger/docker/ssh_templates/docker-compose-experiment.yml.j2"
    ).read_text()
)


CADDYFILE = """
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
def add(host, user):
    """Add a server to deploy experiments through ssh using docker.
    The server needs `docker` and `docker compose` usable by the current user.
    Port 80 and 443 must be free for dallinger to use.
    In case `docker` and/or `docker compose` are missing, dallinger will try to
    install them using `sudo`. The given user must have passwordless sudo rights.
    """
    prepare_server(host, user)
    store_host(dict(host=host, user=user))


@servers.command()
@click.option(
    "--host", required=True, help="IP address or dns name of the remote server"
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

    print("Checking docker presence")
    try:
        executor.run("docker ps")
    except ExecuteException:
        print("Installing docker")
        executor.check_sudo()
        executor.run("wget -O - https://get.docker.com | sudo -n bash")
        executor.run("sudo -n adduser $(id --user --name) docker")
        print("Docker installed")
        # Log in again in case we need to be part of the `docker` group
        executor = Executor(host, user)
    else:
        print("Docker daemon already installed")


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
if len(CONFIGURED_HOSTS) == 1:
    default_server = tuple(CONFIGURED_HOSTS.keys())[0]
    server_prompt = False
else:
    default_server = None
    server_prompt = "Choose one of the configured servers (add one with `dallinger docker-ssh servers add`)\n"
server_option = click.option(
    "--server",
    required=True,
    default=default_server,
    help="Name of the remote server",
    prompt=server_prompt,
    type=click.Choice(tuple(CONFIGURED_HOSTS.keys())),
)


def build_and_push_image(f):
    """Decorator for click commands that depend on a pushed docker image.

    Commands using this decorator can rely on the image being present in
    the remote registry, and thus can use it to deploy to a remote server.

    Checks if the image is already present on the remote repository.
    If it's not builds the image and pushes it.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):  # pragma: no cover
        import docker

        from dallinger.command_line.docker import push
        from dallinger.docker.tools import build_image

        config = get_config()
        config.load()
        image_name = config.get("docker_image_name", None)
        if image_name:
            client = docker.from_env()
            try:
                check_output(["docker", "manifest", "inspect", image_name])
                print(f"Image {image_name} found on remote registry")
                return f(*args, **dict(kwargs, image_name=image_name))
            except CalledProcessError:
                # The image is not on the registry. Check if it's available locally
                # and push it if it is. If images.get succeeds it means the image is available locally
                print(
                    f"Image {image_name} not found on remote registry. Trying to push"
                )
                raw_result = client.images.push(image_name)
                # This is brittle, but it's an edge case not worth more effort
                if not json.loads(raw_result.split("\r\n")[-2]).get("error"):
                    print(f"Image {image_name} pushed to remote registry")
                    return f(*args, **dict(kwargs, image_name=image_name))
                # The image is not available, neither locally nor on the remote registry
                print(
                    f"Could not find image {image_name} specified in experiment config as `docker_image_name`"
                )
                raise click.Abort
        app_name = kwargs.get("app_name", None)
        _, tmp_dir = setup_experiment(
            Output().log,
            exp_config=config.as_dict(),
            local_checks=False,
            app=app_name,
        )
        build_image(tmp_dir, config.get("docker_image_base_name"), out=Output())
        image_name = push.callback(use_existing=True, app_name=app_name)
        return f(image_name, *args, **kwargs)

    return wrapper


def validate_update(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if kwargs["update"] and not kwargs.get("app_name"):
            raise click.UsageError(
                "Please specify the id of the running app to update with --app-name"
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
    dotenv_values = get_dotenv_values(executor)
    dotenv_values["DOZZLE_PASSWORD"] = new_password
    sftp.putfo(BytesIO(json.dumps(dotenv_values).encode()), "dallinger/.env.json")
    dozzle_users = {
        "users": {
            "dallinger": {
                "name": "Dallinger",
                "password": hashlib.sha256(new_password.encode("utf-8")).hexdigest(),
                "email": "dallinger@example.com",
            }
        }
    }
    sftp.putfo(BytesIO(json.dumps(dozzle_users).encode()), "dallinger/dozzle-users.yml")
    executor.restart_dozzle()


@docker_ssh.command("set-dozzle-password")
@server_option
@click.password_option()
def set_dozzle_password_cmd(server, password):
    server_info = CONFIGURED_HOSTS[server]
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")

    executor = Executor(ssh_host, user=ssh_user)
    sftp = get_sftp(ssh_host, user=ssh_user)

    set_dozzle_password(executor, sftp, password)


@docker_ssh.command()
@click.option(
    "--sandbox",
    "mode",
    flag_value="sandbox",
    help="Deploy to MTurk sandbox",
    default=True,
)
@click.option("--live", "mode", flag_value="live", help="Deploy to the real MTurk")
@server_option
@click.option(
    "--dns-host",
    help="DNS name to use. Must resolve all its subdomains to the IP address specified as ssh host",
)
@click.option(
    "--app-name",
    help="Name to use for the app. If not provided a random one will be generated",
)
@click.option(
    "--archive",
    "-a",
    "archive_path",
    type=click.Path(exists=True),
    help="Path to a zip archive created with the `export` command to use as initial database state",
)
@click.option("--config", "-c", "config_options", nargs=2, multiple=True)
@click.option(
    "--update",
    "-u",
    flag_value="update",
    default=False,
    help="Update an existing experiment",
)
@validate_update
@build_and_push_image
def deploy(
    image_name, mode, server, dns_host, app_name, config_options, archive_path, update
):  # pragma: no cover
    """Deploy a dallinger experiment docker image to a server using ssh."""
    config = get_config()
    config.load()
    server_info = CONFIGURED_HOSTS[server]
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")
    dashboard_user = config.get("dashboard_user", "admin")
    dashboard_password = config.get("dashboard_password", secrets.token_urlsafe(8))

    # We deleted this because synchronizing configs between local and remote can cause problems especially when using
    # different credential managers
    # copy_docker_config(ssh_host, ssh_user)
    HAS_TLS = ssh_host != "localhost"
    # We abuse the mturk contact_email_on_error to provide an email for let's encrypt certificate
    email_addr = config.get("contact_email_on_error")
    if HAS_TLS:
        if "@" not in parseaddr(email_addr)[1]:
            print(f"Email address absent or invalid. Value {email_addr} found")
            print("Run `dallinger email-test` to verify your configuration")
            raise click.Abort
    tls = "tls internal" if not HAS_TLS else f"tls {email_addr}"

    experiment_uuid = str(uuid4())
    if app_name:
        experiment_id = app_name
    elif archive_path:
        experiment_id = get_experiment_id_from_archive(archive_path)
    else:
        experiment_id = f"dlgr-{experiment_uuid[:8]}"

    if not dns_host:
        dns_host = get_dns_host(ssh_host)
        print(
            f"{RED}Using {dns_host} as hostname. This might cause problems:{END} some browsers"
        )
        print("might tell users this name is suspicious")
        print("You can override this by creating a DNS A record pointing to")
        print(
            f"{GREEN}{ssh_host}{END} and using option --dns-host to deploy the experiment."
        )
        print(
            f"{BLUE}For instance to use the name experiment1.my-custom-domain.example.com"
        )
        print(
            f"you can pass options --app-name experiment1 --dns-host my-custom-domain.example.com{END}"
        )
    else:
        # Check dns_host: make sure that {experiment_id}.{dns_host} resolves to the remote host
        dns_ok = ipaddr_experiment = ipaddr_server = True
        try:
            ipaddr_server = gethostbyname_ex(f"{ssh_host}")[2][0]
            ipaddr_experiment = gethostbyname_ex(f"{experiment_id}.{dns_host}")[2][0]
        except Exception:
            dns_ok = False
        if not dns_ok or (ipaddr_experiment != ipaddr_server):
            print(
                f"The dns name for the experiment ({experiment_id}.{dns_host}) should resolve to {ipaddr_server}"
            )
            print(f"It currently resolves to {ipaddr_experiment}")
            raise click.Abort
    executor = Executor(ssh_host, user=ssh_user, app=app_name)
    executor.run("mkdir -p ~/dallinger/caddy.d")

    if not update:
        # Check if there's an existing app with the same name
        app_yml = f"~/dallinger/{app_name}/docker-compose.yml"
        app_yml_exists = executor.run(f"ls {app_yml}", raise_=False)
        messages = []
        if app_yml_exists:
            messages.append(
                f"App with name {app_name} already exists: found {app_yml} file. Aborting."
            )
        caddy_yml = f"~/dallinger/caddy.d/{app_name}"
        caddy_yml_exists = executor.run(f"ls {caddy_yml}", raise_=False)
        if caddy_yml_exists:
            print(
                f"App with name {app_name} already exists: found {app_yml} file. Aborting."
            )
        if app_yml_exists or caddy_yml_exists:
            messages.append(
                "Use a different name, destroy the current app or add --update"
            )
            print("\n".join(messages))
            raise click.Abort

        print("Removing any pre-existing Redis volumes.")
        remove_redis_volumes(app_name, executor)
    else:
        app_yml = f"~/dallinger/{app_name}/docker-compose.yml"
        yml_file_exists = executor.run(f"ls -l {app_yml}", raise_=False)
        if not yml_file_exists:
            print(
                f"{app_yml} file not found. App {app_name} does not exist on the server."
            )
            raise click.Abort

    sftp = get_sftp(ssh_host, user=ssh_user)
    sftp.putfo(BytesIO(DOCKER_COMPOSE_SERVER), "dallinger/docker-compose.yml")
    sftp.putfo(
        BytesIO(CADDYFILE.format(host=dns_host, tls=tls).encode()),
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

    cfg = config.as_dict(include_sensitive=True)

    # AWS credential keys need to be converted to upper case
    for key in "aws_access_key_id", "aws_secret_access_key":
        cfg[key.upper()] = cfg.pop(key, None)

    # Remove unneeded sensitive keys
    for key in "database_url", "heroku_auth_token":
        cfg.pop(key, None)

    cfg.update(
        {
            "FLASK_SECRET_KEY": token_urlsafe(16),
            "AWS_DEFAULT_REGION": config["aws_region"],
            "smtp_username": config.get("smtp_username"),
            "activate_recruiter_on_start": config["activate_recruiter_on_start"],
            "auto_recruit": config["auto_recruit"],
            "mode": mode,
            "CREATOR": f"{USER}@{HOSTNAME}",
            "DALLINGER_UID": experiment_uuid,
            "ADMIN_USER": "admin",
            "docker_image_name": image_name,
        }
    )
    cfg.update(config_options)
    del cfg["host"]  # The uppercase variable will be used instead
    executor.run(f"mkdir -p dallinger/{experiment_id}")
    postgresql_password = token_urlsafe(16)
    sftp.putfo(
        BytesIO(
            get_docker_compose_yml(
                cfg, experiment_id, image_name, postgresql_password
            ).encode()
        ),
        f"dallinger/{experiment_id}/docker-compose.yml",
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

    executor.run(
        f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml up -d"
    )
    if archive_path is None and not update:
        print(f"Experiment {experiment_id} started. Initializing database")
        executor.run(
            f"docker compose -f ~/dallinger/{experiment_id}/docker-compose.yml exec -T web dallinger-housekeeper initdb"
        )
        print("Database initialized")

    # We give caddy the alias for the service. If we scale up the service container caddy will
    # send requests to all of them in a round robin fashion.
    caddy_conf = f"{experiment_id}.{dns_host} {{\n    {tls}\n    reverse_proxy {experiment_id}_web:5000\n}}"
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
            f"https://{experiment_id}.{dns_host}/launch", print
        )
        print(launch_data.get("recruitment_msg"))

    dashboard_link = f"https://{dashboard_user}:{dashboard_password}@{experiment_id}.{dns_host}/dashboard"
    log_command = f"ssh {ssh_user + '@' if ssh_user else ''}{ssh_host} docker compose -f '~/dallinger/{experiment_id}/docker-compose.yml' logs -f"

    deployment_infos = [
        f"Deployed Docker image name: {image_name}",
        "To display the logs for this experiment you can run:",
        log_command,
        f"Or you can head to http://logs.{dns_host} (user = dallinger, password = {dozzle_password})",
        f"You can now log in to the console at {dashboard_link} (user = {dashboard_user}, password = {dashboard_password})",
    ]
    for line in deployment_infos:
        print(line)

    deploy_log_path = Path("deploy_logs") / f"{experiment_id}.txt"
    deploy_log_path.parent.mkdir(exist_ok=True)
    with open(deploy_log_path, "w") as f:
        for line in deployment_infos:
            f.write(f"{line}\n")

    return {
        "dashboard_user": dashboard_user,
        "dashboard_password": dashboard_password,
        "dashboard_link": dashboard_link,
        "log_command": log_command,
    }


def get_experiment_id_from_archive(archive_path):
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open("experiment_id.md") as fh:
            return fh.read().decode("utf-8")


def remove_redis_volumes(app_name, executor):
    redis_volume_name = f"{app_name}_dallinger_{app_name}_redis_data"
    stdout = io.StringIO()
    with redirect_stdout(stdout):
        try:
            executor.run(f"docker volume rm '{redis_volume_name}'")
        except ExecuteException:
            err = stdout.getvalue()
            if "no such volume" not in err.lower():
                raise ExecuteException(err)


@docker_ssh.command()
@server_option
def apps(server):
    """List dallinger apps running on the remote server."""
    server_info = CONFIGURED_HOSTS[server]
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")
    executor = Executor(ssh_host, user=ssh_user)
    # The caddy configuration files are used as source of truth
    # to get the list of installed apps
    apps = executor.run("ls ~/dallinger/caddy.d")
    for app in apps.split():
        print(app)
    return apps


@docker_ssh.command()
@server_option
def stats(server):
    """Get resource usage stats from remote server."""
    server_info = CONFIGURED_HOSTS[server]
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")
    executor = Executor(ssh_host, user=ssh_user)
    executor.run_and_echo("docker stats")


@docker_ssh.command()
@click.option("--app", required=True, help="Name of the experiment app to export")
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
@server_option
def export(app, local, no_scrub, server):
    """Export database to a local file."""
    server_info = CONFIGURED_HOSTS[server]
    with remote_postgres(server_info, app) as db_uri:
        export_db_uri(
            app,
            db_uri=db_uri,
            local=local,
            scrub_pii=not no_scrub,
        )


@contextmanager
def remote_postgres(server_info, app):
    """A context manager that opens an ssh tunnel to the remote host and
    returns a database URI to connect to it.
    """
    from sshtunnel import SSHTunnelForwarder

    try:
        ssh_host = server_info["host"]
        ssh_user = server_info.get("user")
        executor = Executor(ssh_host, user=ssh_user, app=app)
        # Prepare a tunnel to be able to pass a postgresql URL to the databse
        # on the remote docker container. First we need to find the IP of the
        # container running docker
        postgresql_remote_ip = executor.run(
            "docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dallinger-postgresql-1"
        ).strip()
        # Now we start the tunnel
        tunnel = SSHTunnelForwarder(
            ssh_host,
            ssh_username=ssh_user,
            remote_bind_address=(postgresql_remote_ip, 5432),
        )
        tunnel.start()
        yield f"postgresql://dallinger:dallinger@localhost:{tunnel.local_bind_port}/{app}"
    finally:
        tunnel.stop()


@docker_ssh.command()
@click.option("--app", required=True, help="Name of the experiment app to destroy")
@server_option
def destroy(server, app):
    """Tear down an experiment run on a server you control via ssh."""
    server_info = CONFIGURED_HOSTS[server]
    ssh_host = server_info["host"]
    ssh_user = server_info.get("user")
    executor = Executor(ssh_host, user=ssh_user, app=app)

    # Check if either the caddy config or the docker compose exist
    # If not, the app is not deployed
    caddy_config_exists = executor.run(
        f"test -f ~/dallinger/caddy.d/{app} && echo Yes", raise_=False
    )
    docker_compose_exists = executor.run(
        f"test -f ~/dallinger/{app}/docker-compose.yml && echo Yes", raise_=False
    )
    if not caddy_config_exists and not docker_compose_exists:
        print(f"App {app} is not deployed")
        raise click.Abort()

    # Remove the caddy configuration file and reload caddy config
    executor.run(f"rm -f ~/dallinger/caddy.d/{app}")
    executor.reload_caddy()

    executor.run(
        f"docker compose -f ~/dallinger/{app}/docker-compose.yml down", raise_=False
    )
    executor.run(f"rm -rf ~/dallinger/{app}/")
    print(f"App {app} removed")


def get_docker_compose_yml(
    config: Dict[str, str],
    experiment_id: str,
    experiment_image: str,
    postgresql_password: str,
) -> str:
    """Generate a docker-compose.yml file based on the given"""
    docker_volumes = config.get("docker_volumes", "")
    config_str = {key: re.sub("\\$", "$$", str(value)) for key, value in config.items()}

    return DOCKER_COMPOSE_EXP_TPL.render(
        experiment_id=experiment_id,
        experiment_image=experiment_image,
        config=config_str,
        docker_volumes=docker_volumes,
        postgresql_password=postgresql_password,
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


def get_dns_host(ssh_host):
    ip_addr = gethostbyname_ex(ssh_host)[2][0]
    return f"{ip_addr}.nip.io"


class Executor:
    """Execute remote commands using paramiko"""

    def __init__(self, host, user=None, app=None):
        import paramiko

        self.app = app
        self.client = paramiko.SSHClient()
        # For convenience we always trust the remote host
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.load_system_host_keys()
        self.host = host
        print(f"Connecting to {host}")
        self.client.connect(host, username=user)
        print("Connected.")

    def run(self, cmd, raise_=True):
        """Run the given command and block until it completes.
        If `raise` is True and the command fails, print the reason and raise an exception.
        """
        channel = self.client.get_transport().open_session()
        channel.exec_command(cmd)
        status = channel.recv_exit_status()
        if raise_ and status != 0:
            print(f"Error: exit code was not 0 ({status})")
            print(channel.recv(10**10).decode())
            print(channel.recv_stderr(10**10).decode())
            self.print_docker_compose_logs()
            raise ExecuteException(
                f"An error occurred when running the following command on the remote server: \n{cmd}"
            )
        return channel.recv(10**10).decode()

    def print_docker_compose_logs(self):
        if self.app:
            channel = self.client.get_transport().open_session()
            channel.exec_command(
                f'docker compose -f "$HOME/dallinger/{self.app}/docker-compose.yml" logs'
            )
            status = channel.recv_exit_status()
            if status != 0:
                print("`docker compose` logs failed to run.")
            else:
                print("*** BEGIN docker compose logs ***")
                print(channel.recv(10**10).decode())
                print("*** END docker compose logs ***\n")

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


class ExecuteException(Exception):
    pass


def get_sftp(host, user=None):
    import paramiko

    client = paramiko.SSHClient()
    # For convenience we always trust the remote host
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.load_system_host_keys()
    client.connect(host, username=user)
    return client.open_sftp()


logging.getLogger("paramiko.transport").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
