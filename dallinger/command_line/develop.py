import click
import logging

from six.moves.urllib.parse import urlparse
from six.moves.urllib.parse import urlunparse

from dallinger.command_line.utils import header
from dallinger.command_line.utils import log
from dallinger.command_line.utils import Output
from dallinger.command_line.utils import require_exp_directory
from dallinger.config import get_config
from dallinger.deployment import DevelopmentDeployment
from dallinger.deployment import _handle_launch_data
from dallinger.utils import open_browser


logger = logging.getLogger(__name__)
BASE_URL = "http://127.0.0.1:{}/"


def ad_url(config, port):
    return BASE_URL.format(port) + "ad?generate_tokens=true&recruiter=hotair"


def dashboard_url(config, port):
    parsed = list(urlparse(BASE_URL.format(port) + "dashboard/develop"))
    parsed[1] = "{}:{}@{}".format(
        config.get("dashboard_user"),
        config.get("dashboard_password"),
        parsed[1],
    )
    return urlunparse(parsed)


valid_routes = {
    "ad": ad_url,
    "dashboard": dashboard_url,
}


@click.group()
def develop():
    pass


@develop.command()
@click.option("--port", default=5000, help="The port Flask is running on")
def launch(port):
    """Send a POST to the /launch route"""
    url = BASE_URL.format(port) + "launch"
    result = _handle_launch_data(url, error=log, attempts=1)
    if result and "status" in result:
        log(result["status"])


@develop.command()
@require_exp_directory
def bootstrap(exp_config=None):
    """Run the experiment locally."""
    bootstrapper = DevelopmentDeployment(Output(), exp_config)
    log(header, chevrons=False)
    bootstrapper.run()


@develop.command()
@click.option(
    "--route",
    default=None,
    help="Route name (valid routes are: {})".format(", ".join(valid_routes.keys())),
)
@click.option("--port", default=5000, help="The port Flask is running on")
def browser(route=None, port=5000):
    """Open one of the supported routes with appropriate path and URL parameters"""
    config = get_config()
    config.load()
    url_factory = valid_routes.get(route)
    if url_factory is not None:
        open_browser(url_factory(config, port))
    else:
        click.echo(
            "Supported routes are:\n\t{}".format("\n\t".join(valid_routes.keys()))
        )
