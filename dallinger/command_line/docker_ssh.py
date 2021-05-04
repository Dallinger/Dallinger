from io import BytesIO
from uuid import uuid4

from jinja2 import Template
import click
import paramiko

from dallinger.utils import abspath_from_egg


DOCKER_COMPOSE_SERVER = abspath_from_egg(
    "dallinger", "dallinger/docker/ssh_templates/docker-compose-server.yml"
).read_bytes()

DOCKER_COMPOSE_EXP_TPL = Template(
    abspath_from_egg(
        "dallinger", "dallinger/docker/ssh_templates/docker-compose-experiment.yml.j2"
    ).read_text()
)


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
    print(f"Connecting to {host}")
    client.connect(host)
    print("Connected. Launching postgresql and http server")
    client.exec_command("mkdir -p dallinger")
    sftp = client.open_sftp()
    sftp.putfo(BytesIO(DOCKER_COMPOSE_SERVER), "dallinger/docker-compose.yml")
    sftp.putfo(BytesIO(CADDYFILE), "dallinger/Caddyfile")
    channel = client.get_transport().open_session()
    channel.exec_command("docker-compose -f dallinger/docker-compose.yml up -d")
    status = channel.recv_exit_status()
    if status != 0:
        print(f"Error: exit code was not 0 ({status})")
        print(channel.recv(10 ** 10).decode())
        print(channel.recv_stderr(10 ** 10).decode())
        raise click.Abort
    print("Launched http and postgresql servers")

    experiment_id = uuid4().hex[:8]
    channel = client.get_transport().open_session()
    channel.exec_command(f"mkdir -p dallinger/{experiment_id}")
    status = channel.recv_exit_status()
    sftp.putfo(
        BytesIO(
            DOCKER_COMPOSE_EXP_TPL.render(
                experiment_id=experiment_id, experiment_image=image
            ).encode()
        ),
        f"dallinger/{experiment_id}/docker-compose.yml",
    )
    channel = client.get_transport().open_session()
    channel.exec_command(
        f"docker-compose -f dallinger/{experiment_id}/docker-compose.yml up -d"
    )
    status = channel.recv_exit_status()
    if status != 0:
        print(
            f"Error while starting experiment servers: exit code was not 0 ({status})"
        )
        print(channel.recv(10 ** 10).decode())
        print(channel.recv_stderr(10 ** 10).decode())
        raise click.Abort

    client.close()
    print("To display the logs for this experiment you can run:")
    print(
        f"ssh {host} docker-compose -f dallinger/{experiment_id}/docker-compose.yml logs -f"
    )
