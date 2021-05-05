from io import BytesIO
from getpass import getuser
from uuid import uuid4
from secrets import token_urlsafe
from socket import gethostname
from socket import gethostbyname_ex
from typing import Dict

from jinja2 import Template
import click
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import requests

from dallinger.config import get_config
from dallinger.utils import abspath_from_egg


HOSTNAME = gethostname()
USER = getuser()

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
{host} {{
    respond /health-check 200
    {tls}
}}

import caddy.d/*
"""


@click.group()
def docker_ssh():
    """Deploy to a remote server using docker through ssh."""


@docker_ssh.command()
@click.option("--ssh-host", required=True, help="Server name to prepare for deployment")
def prepare_server(ssh_host):
    executor = Executor(ssh_host)
    print("Installing docker-compose")
    executor.run("python3 -m pip install --user docker-compose")
    print("docker-compose installed")


@docker_ssh.command()
@click.option(
    "--sandbox",
    "mode",
    flag_value="sandbox",
    help="Deploy to MTurk sandbox",
    default=True,
)
@click.option("--live", "mode", flag_value="live", help="Deploy to the real MTurk")
@click.option("--image", required=True, help="Name of the docker image to deploy")
@click.option("--ssh-host", required=True, help="Server name to deploy to")
@click.option(
    "--dns-host",
    help="DNS name to use. Must resolve all its subdomains to the IP address specified as ssh host",
)
@click.option("--config", "-c", "config_options", nargs=2, multiple=True)
def deploy(mode, image, ssh_host, dns_host, config_options):
    HAS_TLS = ssh_host != "localhost"
    tls = "tls internal" if not HAS_TLS else ""
    if not dns_host:
        dns_host = get_dns_host(ssh_host)
    executor = Executor(ssh_host)
    executor.run("mkdir -p dallinger/caddy.d")

    sftp = get_sftp(ssh_host)
    sftp.putfo(BytesIO(DOCKER_COMPOSE_SERVER), "dallinger/docker-compose.yml")
    sftp.putfo(
        BytesIO(CADDYFILE.format(host=dns_host, tls=tls).encode()),
        "dallinger/Caddyfile",
    )
    executor.run("docker-compose -f ~/dallinger/docker-compose.yml up -d")
    print("Launched http and postgresql servers. Starting experiment")

    experiment_uuid = str(uuid4())
    experiment_id = f"dlgr-{experiment_uuid[:8]}"
    dashboard_password = token_urlsafe(8)
    config = get_config()
    config.load()
    cfg = config.as_dict()
    cfg.update(
        {
            "FLASK_SECRET_KEY": token_urlsafe(16),
            "dashboard_password": dashboard_password,
            "mode": mode,
            "CREATOR": f"{USER}@{HOSTNAME}",
            "DALLINGER_UID": experiment_uuid,
            "ADMIN_USER": "admin",
        }
    )
    cfg.update(config_options)
    del cfg["host"]  # The uppercase variable will be used instead
    executor.run(f"mkdir -p dallinger/{experiment_id}")
    sftp.putfo(
        BytesIO(get_docker_compose_yml(cfg, experiment_id, image).encode()),
        f"dallinger/{experiment_id}/docker-compose.yml",
    )
    executor.run(
        f"docker-compose -f ~/dallinger/{experiment_id}/docker-compose.yml up -d"
    )
    print(f"Experiment {experiment_id} started. Initializing database")
    executor.run(
        f"docker-compose -f ~/dallinger/{experiment_id}/docker-compose.yml exec -T web dallinger-housekeeper initdb"
    )
    print("Database initialized")

    caddy_conf = f"{experiment_id}.{dns_host} {{\n    {tls}\n    reverse_proxy {experiment_id}_web:5000\n}}"
    sftp.putfo(
        BytesIO(caddy_conf.encode()),
        f"dallinger/caddy.d/{experiment_id}",
    )

    # Tell caddy we changed something in the configuration
    executor.run(
        "docker-compose -f ~/dallinger/docker-compose.yml exec -T httpserver caddy reload -config /etc/caddy/Caddyfile"
    )

    print("Launching experiment")
    response = get_retrying_http_client().post(
        f"https://{experiment_id}.{dns_host}/launch", verify=HAS_TLS
    )
    print(response.json()["recruitment_msg"])

    print("To display the logs for this experiment you can run:")
    print(
        f"ssh {ssh_host} docker-compose -f ~/dallinger/{experiment_id}/docker-compose.yml logs -f"
    )
    print(
        f"You can now log in to the console at https://{experiment_id}.{dns_host}/dashboard as user {cfg['ADMIN_USER']} using password {cfg['dashboard_password']}"
    )


def get_docker_compose_yml(
    config: Dict[str, str], experiment_id: str, experiment_image: str
) -> str:
    """Generate a docker-compose.yml file based on the given"""
    return DOCKER_COMPOSE_EXP_TPL.render(
        experiment_id=experiment_id, experiment_image=experiment_image, config=config
    )


def get_retrying_http_client():
    retry_strategy = Retry(
        total=10,
        backoff_factor=0.2,
        status_forcelist=[429, 500, 502, 503, 504],
        method_whitelist=["POST"],
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

    def __init__(self, host):
        import paramiko

        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        print(f"Connecting to {host}")
        self.client.connect(host)
        print("Connected.")

    def run(self, cmd):
        """Run the given command and block until it completes.
        If the command fails, print the reason and raise an exception
        """
        channel = self.client.get_transport().open_session()
        channel.exec_command(cmd)
        status = channel.recv_exit_status()
        print(f"Executing {cmd}")
        if status != 0:
            print(f"Error: exit code was not 0 ({status})")
            print(channel.recv(10 ** 10).decode())
            print(channel.recv_stderr(10 ** 10).decode())
            raise ExecuteException
        return channel.recv(10 ** 10).decode()


class ExecuteException(Exception):
    pass


def get_sftp(host):
    import paramiko

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect(host)
    return client.open_sftp()
