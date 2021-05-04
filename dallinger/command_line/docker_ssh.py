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


CADDYFILE = """
# This is a configuration file for the Caddy http Server
# Documentation can be found at https://caddyserver.com/docs
{host} {{
    tls internal
}}

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
    executor = Executor(host)
    executor.run("mkdir -p dallinger/caddy.d")

    sftp = get_sftp(host)
    sftp.putfo(BytesIO(DOCKER_COMPOSE_SERVER), "dallinger/docker-compose.yml")
    sftp.putfo(BytesIO(CADDYFILE.format(host=host).encode()), "dallinger/Caddyfile")
    executor.run("docker-compose -f dallinger/docker-compose.yml up -d")
    print("Launched http and postgresql servers. Starting experiment")

    experiment_id = uuid4().hex[:8]
    executor.run(f"mkdir -p dallinger/{experiment_id}")
    sftp.putfo(
        BytesIO(
            DOCKER_COMPOSE_EXP_TPL.render(
                experiment_id=experiment_id, experiment_image=image
            ).encode()
        ),
        f"dallinger/{experiment_id}/docker-compose.yml",
    )
    executor.run(
        f"docker-compose -f dallinger/{experiment_id}/docker-compose.yml up -d"
    )
    print(f"Experiment {experiment_id} started")

    executor.run(
        f"docker-compose -f dallinger/{experiment_id}/docker-compose.yml up -d"
    )

    caddy_conf = f"{experiment_id}.{host} {{\n    tls internal\n    reverse_proxy {experiment_id}_web:5000\n}}"
    sftp.putfo(
        BytesIO(caddy_conf.encode()),
        f"dallinger/caddy.d/{experiment_id}",
    )

    # Tell caddy we changed something in the configuration
    executor.run(
        "docker-compose -f dallinger/docker-compose.yml exec -T httpserver caddy reload -config /etc/caddy/Caddyfile"
    )

    print("To display the logs for this experiment you can run:")
    print(
        f"ssh {host} docker-compose -f dallinger/{experiment_id}/docker-compose.yml logs -f"
    )


class Executor:
    """Execute remote commands using paramiko"""

    def __init__(self, host):
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
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.connect(host)
    return client.open_sftp()
