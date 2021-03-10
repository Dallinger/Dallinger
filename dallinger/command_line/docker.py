import click
import os

from dallinger.command_line.utils import Output
from dallinger.command_line.utils import header
from dallinger.command_line.utils import log
from dallinger.command_line.utils import require_exp_directory


@click.group()
def docker():
    """Use docker for local debug and deployment."""


@docker.command()
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option(
    "--bot",
    is_flag=True,
    flag_value=True,
    help="Use bot to complete experiment",
)
@click.option(
    "--proxy",
    default=None,
    help="Alternate port when opening browser windows",
)
@click.option(
    "--no-browsers",
    is_flag=True,
    flag_value=True,
    default=False,
    help="Skip opening browsers",
)
@require_exp_directory
def debug(verbose, bot, proxy, no_browsers=False, exp_config=None):
    """Run the experiment locally using docker compose."""
    from dallinger.docker.deployment import DockerDebugDeployment

    debugger = DockerDebugDeployment(
        Output(), verbose, bot, proxy, exp_config, no_browsers
    )
    log(header, chevrons=False)
    debugger.run()


@docker.command()
def start_services():
    """Starts postgresql and redis services using docker"""
    os.system(
        "docker run --rm -d --name dallinger_redis -p 6379:6379 -v dallinger_redis:/data redis redis-server --appendonly yes"
    )
    os.system(
        "docker run -d --name dallinger_postgres -p 5432:5432 -e POSTGRES_USER=dallinger -e POSTGRES_PASSWORD=dallinger -e POSTGRES_DB=dallinger -v dallinger_postgres:/var/lib/postgresql/data postgres:12"
    )
