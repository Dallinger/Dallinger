import click

from dallinger.deployment import DockerDeployment
from dallinger.command_line.utils import Output
from dallinger.command_line.utils import error
from dallinger.command_line.utils import log


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
def debug(verbose, bot, proxy, no_browsers=False, exp_config=None):
    """Run the experiment locally using docker compose."""
    debugger = DockerDeployment(Output(), verbose, bot, proxy, exp_config, no_browsers)
    log(header, chevrons=False)
    debugger.run()
