from contextlib import contextmanager
from functools import wraps
from getpass import getuser
from os.path import expanduser
from secrets import token_urlsafe
from shlex import quote
from socket import gethostname
from typing import Dict
from uuid import uuid4
import logging
import shlex
import socket
import subprocess
import os
import zipfile
from dallinger import recruiters

import dns.resolver
from jinja2 import Template
from requests.adapters import HTTPAdapter
import urllib3
from urllib3.util.retry import Retry
import click
import requests

from dallinger.data import bootstrap_db_from_zip
from dallinger.db import create_db_engine
from dallinger.command_line.docker import add_image_name
from dallinger.command_line.utils import Output
from dallinger.config import LOCAL_CONFIG
from dallinger.data import export_db_uri
from dallinger.deployment import setup_experiment
from dallinger.config import get_config
from dallinger.utils import abspath_from_egg


# Find an identifier for the current user to use as CREATOR of the experiment
HOSTNAME = gethostname()
try:
    USER = getuser()
except KeyError:
    USER = "user"

DOCKER_COMPOSE_SERVER = abspath_from_egg(
    "dallinger", "dallinger/docker/ssh_templates/docker-compose-server.yml"
).read_text()

DOCKER_COMPOSE_EXP_TPL = Template(
    abspath_from_egg(
        "dallinger", "dallinger/docker/ssh_templates/docker-compose-experiment.yml.j2"
    ).read_text()
)


CADDYFILE = Template(
    """
{
  debug
  default_sni 172.18.0.250
}
# This is a configuration file for the Caddy http Server
# Documentation can be found at https://caddyserver.com/docs

{{ local_ip_name }} 172.18.0.250 localhost {
  tls internal
  route /health-check {
      respond /health-check 200
  }
  import experiments.d/*
  respond 404
}
"""
)

EXPERIMENT_CADDY_CONF_TEMPLATE = Template(
    """
route /{{ experiment_id }}* {
  reverse_proxy /{{ experiment_id }}* {{ experiment_id }}_web:5000
  respond 404
}
"""
)


@click.group()
@click.pass_context
def docker_local(ctx):
    """Deploy to local machine using docker."""


@docker_local.command()
def prepare():
    """Prepare the local machine to host a dallinger experiment.
    In case docker and/or docker-compose are missing, dallnger will try to
    install them using `sudo`. The given user must have passwordless sudo rights.
    """
    executor = Executor()
    print("Checking docker presence")
    try:
        executor.run("docker ps")
    except ExecuteException:
        print("Installing docker")
        executor.check_sudo()
        executor.run("wget -O - https://get.docker.com | sudo -n bash")
        executor.run("sudo -n adduser $(id --user --name) docker")
        print("Docker installed")
    else:
        print("Docker daemon already installed")

    try:
        executor.run("docker-compose --version")
    except ExecuteException:
        try:
            install_docker_compose_via_pip(executor)
        except ExecuteException:
            executor.check_sudo()
            executor.run(
                "sudo -n wget https://github.com/docker/compose/releases/download/1.29.1/docker-compose-Linux-x86_64 -O /usr/local/bin/docker-compose"
            )
            executor.run("sudo -n chmod 755 /usr/local/bin/docker-compose")
    else:
        print("Docker compose already installed")


def install_docker_compose_via_pip(executor):
    try:
        executor.run("python3 --version")
    except ExecuteException:
        # No python: better give up
        return

    try:
        executor.run("python3 -m pip --version")
    except ExecuteException:
        # No pip. Let's try to install it
        executor.run("python3 <(wget -O - https://bootstrap.pypa.io/get-pip.py)")
    executor.run("python3 -m pip install --user docker-compose")
    executor.run("sudo ln -s ~/.local/bin/docker-compose /usr/local/bin/docker-compose")
    print("docker-compose installed using pip")


def build_image(f):
    """Decorator for click commands that depend on a pushed docker image.

    Commands using this decorator can rely on the image being present in
    the remote registry, and thus can use it to deploy to a remote server.

    Checks if the image is already present on the remote repository.
    If it's not builds the image and pushes it.
    """

    @wraps(f)
    def wrapper(*args, **kwargs):  # pragma: no cover
        from dallinger.docker.tools import build_image
        from dallinger.command_line.docker import push
        import docker

        config = get_config()
        config.load()
        image_name = config.get("docker_image_name", None)
        if image_name:
            client = docker.from_env()
            try:
                client.images.get(image_name)
                return f(*args, **kwargs)
            except requests.exceptions.HTTPError:
                print(
                    f"Could not find image {image_name} specified in experiment config as `docker_image_name`"
                )
                raise click.Abort
        _, tmp_dir = setup_experiment(
            Output().log, exp_config=config.as_dict(), local_checks=False
        )
        build_image(tmp_dir, config.get("docker_image_base_name"), out=Output())

        pushed_image = push.callback(use_existing=True)
        add_image_name(LOCAL_CONFIG, pushed_image)
        return f(*args, **kwargs)

    return wrapper


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(("8.8.8.8", 80))
    result = sock.getsockname()[0]
    sock.close()
    return result


def get_local_ip_name():
    """Returns a DNS name that can be used on the local network to reach this host.
    Uses the 224.0.0.251 multicast address to get the name registered on mDNS.
    """
    local_ip = get_local_ip()
    ip_to_query = ".".join(local_ip.split(".")[::-1]) + ".in-addr.arpa"
    resolver = dns.resolver.Resolver()
    resolver.nameservers = ["224.0.0.251"]  # mdns multicast address
    resolver.port = 5353  # mdns port
    try:
        answers = resolver.query(ip_to_query, "PTR")
    except (dns.resolver.NXDOMAIN, dns.resolver.LifetimeTimeout):
        return local_ip
    else:
        # Make sure to remove the trailing dot, or it will confuse Caddy
        return answers[0].target.to_text().rstrip(".")


@docker_local.command()
@click.option(
    "--sandbox",
    "mode",
    flag_value="sandbox",
    help="Deploy to MTurk sandbox",
    default=True,
)
@click.option("--live", "mode", flag_value="live", help="Deploy to the real MTurk")
@click.option(
    "--archive",
    "-a",
    "archive_path",
    type=click.Path(exists=True),
    help="Path to a zip archive created with the `export` command to use as initial database state",
)
@click.option("--config", "-c", "config_options", nargs=2, multiple=True)
@build_image
def deploy(mode, config_options, archive_path):  # pragma: no cover
    """Deploy a dallnger experiment docker image to the local machine."""
    config = get_config()
    config.load()
    recruiter = recruiters.from_config(config)
    if recruiter.needs_public_ip:
        print(
            "The local deployment will only work with recruiters that don't need a public IP address"
        )
        raise click.Abort
    executor = Executor()
    executor.run("mkdir -p ~/dallinger/experiments.d")

    open(expanduser("~/dallinger/docker-compose.yml"), "w").write(DOCKER_COMPOSE_SERVER)
    local_ip_name = get_local_ip_name()

    global_caddy_conf = CADDYFILE.render(
        local_ip_name=local_ip_name,
    )

    open(expanduser("~/dallinger/Caddyfile"), "w").write(global_caddy_conf)
    executor.run("docker-compose -f ~/dallinger/docker-compose.yml up -d")
    print("Launched http and postgresql servers. Starting experiment")

    experiment_uuid = str(uuid4())
    if archive_path:
        experiment_id = get_experiment_id_from_archive(archive_path)
    else:
        experiment_id = f"dlgr-{experiment_uuid[:8]}"
    dashboard_password = token_urlsafe(8)
    image = config.get("docker_image_name", None)
    cfg = config.as_dict()
    for key in "aws_access_key_id", "aws_secret_access_key":
        # AWS credentials are not included by default in to_dict() result
        # but can be extracted explicitly from a config object
        cfg[key.upper()] = config[key]

    cfg.update(
        {
            "FLASK_SECRET_KEY": token_urlsafe(16),
            "AWS_DEFAULT_REGION": config["aws_region"],
            "dashboard_password": dashboard_password,
            "mode": mode,
            "CREATOR": f"{USER}@{HOSTNAME}",
            "DALLINGER_UID": experiment_uuid,
            "ADMIN_USER": "admin",
        }
    )
    cfg.update(config_options)
    del cfg["host"]  # The uppercase variable will be used instead
    executor.run(f"mkdir -p ~/dallinger/{experiment_id}")
    postgresql_password = token_urlsafe(16)
    open(expanduser(f"~/dallinger/{experiment_id}/docker-compose.yml"), "w").write(
        get_docker_compose_yml(cfg, experiment_id, image, postgresql_password)
    )

    # We invoke the "ls" command in the context of the `web` container.
    # docker-compose will honour `web`'s dependencies and block
    # until postgresql is ready. This way we can be sure we can start creating the database.
    executor.run(
        f"docker-compose -f ~/dallinger/{experiment_id}/docker-compose.yml run --rm web ls"
    )
    print("Cleaning up db/user")
    executor.run(
        rf"""docker-compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c 'DROP DATABASE IF EXISTS "{experiment_id}";'"""
    )
    executor.run(
        rf"""docker-compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c 'DROP USER IF EXISTS "{experiment_id}"; '"""
    )
    print(f"Creating database {experiment_id}")
    executor.run(
        rf"""docker-compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c 'CREATE DATABASE "{experiment_id}"'"""
    )
    create_user_script = f"""CREATE USER "{experiment_id}" with encrypted password '{postgresql_password}'"""
    executor.run(
        f"docker-compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c {quote(create_user_script)}"
    )
    grant_roles_script = (
        f'grant all privileges on database "{experiment_id}" to "{experiment_id}"'
    )

    if archive_path is not None:
        print(f"Loading database data from {archive_path}")
        db_uri = postgres_uri(experiment_id)
        engine = create_db_engine(db_uri)
        bootstrap_db_from_zip(archive_path, engine)
        with engine.connect() as conn:
            conn.execute(grant_roles_script)
            conn.execute(f'GRANT USAGE ON SCHEMA public TO "{experiment_id}"')
            conn.execute(
                f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA PUBLIC TO "{experiment_id}"'
            )

    executor.run(
        f"docker-compose -f ~/dallinger/docker-compose.yml exec -T postgresql psql -U dallinger -c {quote(grant_roles_script)}"
    )

    executor.run(
        f"docker-compose -f ~/dallinger/{experiment_id}/docker-compose.yml up -d"
    )
    if archive_path is None:
        print(f"Experiment {experiment_id} started. Initializing database")
        executor.run(
            f"docker-compose -f ~/dallinger/{experiment_id}/docker-compose.yml exec -T web dallinger-housekeeper initdb"
        )
        print("Database initialized")

    # We give caddy the alias for the service. If we scale up the service container caddy will
    # send requests to all of them in a round robin fashion.
    caddy_conf = EXPERIMENT_CADDY_CONF_TEMPLATE.render(
        experiment_id=experiment_id,
    )
    open(expanduser(f"~/dallinger/experiments.d/{experiment_id}"), "w").write(
        caddy_conf
    )
    # Tell caddy we changed something in the configuration
    executor.reload_caddy()

    print(f"Launching experiment at https://{local_ip_name}/{experiment_id}/launch")
    urllib3.disable_warnings()
    response = get_retrying_http_client().post(
        f"https://{local_ip_name}/{experiment_id}/launch", verify=False
    )
    recruitment_msg = response.json()["recruitment_msg"]
    # Add experiment id to URLs in recruitment message
    # This should be better done in dallinger.utils:get_base_url
    # by using flask routes.
    recruitment_msg = recruitment_msg.replace(
        f"https://{local_ip_name}/", f"https://{local_ip_name}/{experiment_id}/"
    )
    print(recruitment_msg)

    print("To display the logs for this experiment you can run:")
    print(
        expanduser(
            f"docker-compose -f ~/dallinger/{experiment_id}/docker-compose.yml logs -f"
        )
    )
    print(
        f"You can now log in to the console at https://{local_ip_name}/{experiment_id}/dashboard as user {cfg['ADMIN_USER']} using password {cfg['dashboard_password']}"
    )


def get_experiment_id_from_archive(archive_path):
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open("experiment_id.md") as fh:
            return fh.read().decode("utf-8")


@docker_local.command()
def apps():
    """List dallinger apps running locally."""
    executor = Executor()
    # The caddy configuration files are used as source of truth
    # to get the list of installed apps
    apps = executor.run("ls ~/dallinger/experiments.d")
    for app in apps.split():
        print(app)


@docker_local.command()
def stats():
    """Get resource usage stats."""
    os.execvp("docker", ["docker", "stats"])


@docker_local.command()
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
def export(app, local, no_scrub):
    """Export database to a local file."""
    export_db_uri(
        app,
        db_uri=postgres_uri(app),
        local=local,
        scrub_pii=not no_scrub,
    )


@contextmanager
def postgres_uri(app):
    """A context manager that returns a database URI to connect to it."""
    executor = Executor()
    postgresql_ip = executor.run(
        "docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dallinger_postgresql_1"
    ).strip()
    yield f"postgresql://dallinger:dallinger@{postgresql_ip}:5432/{app}"


@docker_local.command()
@click.option("--app", required=True, help="Name of the experiment app to destroy")
def destroy(app):
    """Tear down an experiment run locally."""
    executor = Executor()
    # Remove the caddy configuration file and reload caddy config
    try:
        executor.run(f"ls ~/dallinger/experiments.d/{app}")
    except ExecuteException:
        print(f"App {app} not found")
        raise click.Abort
    executor.run(f"rm ~/dallinger/experiments.d/{app}")
    executor.reload_caddy()
    executor.run(
        f"docker-compose -f ~/dallinger/{app}/docker-compose.yml down", raise_=False
    )
    executor.run(f"rm -rf ~/dallinger/{app}/")
    print(f"App {app} removed")


def get_docker_compose_yml(
    config: Dict[str, str],
    experiment_id: str,
    experiment_image: str,
    postgresql_password: str,
) -> str:
    """Generate a docker-compose.yml file based on the given parameters"""
    return DOCKER_COMPOSE_EXP_TPL.render(
        experiment_id=experiment_id,
        experiment_image=experiment_image,
        config=dict(config, DALLINGER_PATH_PREFIX=f"/{experiment_id}"),
        postgresql_password=postgresql_password,
    )


def get_retrying_http_client():
    retry_strategy = Retry(
        total=30,
        backoff_factor=0.2,
        status_forcelist=[429, 500, 502, 503, 504],
        method_whitelist=["POST"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    http = requests.Session()
    http.mount("https://", adapter)
    http.mount("http://", adapter)
    return http


class Executor:
    """Execute local commands"""

    def run(self, cmd, raise_=True):
        """Run the given command and block until it completes.
        If `raise` is True and the command fails, raise an exception.
        """
        if isinstance(cmd, str):
            commands = tuple(map(expanduser, shlex.split(cmd)))
        else:
            commands = cmd
        try:
            result = subprocess.run(
                commands, stdout=subprocess.PIPE, stderr=subprocess.PIPE
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            if raise_:
                raise ExecuteException
        if result.returncode != 0 and raise_:
            raise ExecuteException(result.stderr.decode("utf-8"))
        return result.stdout.decode("utf-8")

    def check_sudo(self):
        """Make sure the current user is authorized to invoke sudo without providing a password.
        If that is not the case print a message and raise click.Abort
        """
        if not self.run("sudo -n ls -l /", raise_=False):
            print(
                "No passwordless sudo rights on localhost. Make sure your user can run sudo without a password.\n"
                "Run `sudo visudo` and add this to the end of the file (replacing with your username):\n"
                "<username> ALL=NOPASSWD: ALL"
            )
            raise click.Abort

    def reload_caddy(self):
        self.run(
            expanduser(
                "docker-compose -f ~/dallinger/docker-compose.yml exec -T httpserver "
            )
            + "caddy reload -config /etc/caddy/Caddyfile"
        )


class ExecuteException(Exception):
    pass


logging.getLogger("paramiko.transport").setLevel(logging.ERROR)
logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
