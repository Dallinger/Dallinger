import click

from dallinger.deployment import DockerDebugDeployment
from dallinger.command_line.utils import Output
from dallinger.command_line.utils import error
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
    debugger = DockerDebugDeployment(
        Output(), verbose, bot, proxy, exp_config, no_browsers
    )
    log(header, chevrons=False)
    debugger.run()
