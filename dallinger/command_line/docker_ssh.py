from io import BytesIO

import click
import paramiko

from dallinger.utils import abspath_from_egg


DOCKER_COMPOSE_SERVER = abspath_from_egg(
    "dallinger", "dallinger/docker/ssh_templates/docker-compose-server.yml"
).read_bytes()

CADDYFILE = b"""
# This is a configuration file for the Caddy http Server
# Documentation can be found at https://caddyserver.com/docs
localhost {
    tls internal
}

import caddy.d/*
"""


@click.group()
def docker_ssh():
    """Deploy to a remote server using docker through ssh."""


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
@click.option("--host", required=True, help="Server name to deploy to")
@click.option("--config", "-c", "config_options", nargs=2, multiple=True)
def deploy(mode, image, host, config_options):
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect(host)
    client.exec_command("mkdir -p dallinger")
    sftp = client.open_sftp()
    sftp.putfo(BytesIO(DOCKER_COMPOSE_SERVER), "dallinger/docker-compose.yml")
    sftp.putfo(BytesIO(CADDYFILE), "dallinger/Caddyfile")
    channel = client.get_transport().open_session()
    channel.exec_command("docker-compose -f dallinger/docker-compose.yml up -d")
    status = channel.recv_exit_status()
    print(f"Status: {status}")
    channel.close()
    client.close()
