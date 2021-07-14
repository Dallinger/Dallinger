import click

from dallinger.command_line.utils import header
from dallinger.command_line.utils import log
from dallinger.command_line.utils import Output
from dallinger.command_line.utils import require_exp_directory
from dallinger.config import get_config
from dallinger.deployment import DevelopmentDeployment
from dallinger.utils import open_browser


BASE_URL = "http://127.0.0.1:7000/"


valid_routes = {
    "ad": "ad?generate_tokens=true&recruiter=hotair",
    "dashboard": "dashboard/develop",
}


@click.group()
def develop():
    pass


@develop.command()
@require_exp_directory
def bootstrap(exp_config=None):
    """Run the experiment locally."""
    bootstrapper = DevelopmentDeployment(Output(), exp_config)
    log(header, chevrons=False)
    bootstrapper.run()


@develop.command()
@click.option("--route", default=None, help="Route name")
def browser(route=None):
    """Open one of the supported routes with appropriate path and URL parameters"""
    config = get_config()
    config.load()
    url_tail = valid_routes.get(route)
    if url_tail is not None:
        url = BASE_URL + valid_routes.get(route)
        open_browser(url)
    else:
        click.echo(
            "Supported routes are:\n\t{}".format("\n\t".join(valid_routes.keys()))
        )
