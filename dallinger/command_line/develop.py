import subprocess
import threading
import time

import click
from rq import Queue
from six.moves.urllib.parse import urlparse, urlunparse

from dallinger.command_line.utils import (
    Output,
    error,
    header,
    log,
    require_exp_directory,
)
from dallinger.config import get_config
from dallinger.db import redis_conn
from dallinger.deployment import DevelopmentDeployment, handle_launch_data
from dallinger.utils import develop_target_path, open_browser, setup_warning_hooks

setup_warning_hooks()

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
@click.option(
    "--skip-flask",
    is_flag=True,
    help="Skip launching Flask, so that Flask can be managed externally",
)
def debug(port, skip_flask):
    from dallinger.command_line.utils import verify_package

    if not verify_package():
        # We could instead use the @require_exp_directory decorator,
        # but this doesn't print anything useful without the verbose flag.
        # To consider for later: improving this default behavior of @require_exp_directory?
        print(
            "Cannot continue, there is a problem with the current experiment (see above)."
        )
        raise click.Abort

    _bootstrap()

    q = Queue("default", connection=redis_conn)
    job = q.enqueue_call(launch_app_and_open_browser, kwargs={"port": port})

    if not skip_flask:
        config = get_config()
        develop_dir = develop_target_path(config)
        try:
            subprocess.check_call(["./run.sh"], cwd=develop_dir)
        except subprocess.CalledProcessError as ex:
            job.cancel()
            error("Failed to run flask: {} See traceback above for details.".format(ex))


@develop.command()
@require_exp_directory
def bootstrap(exp_config=None):
    _bootstrap(exp_config)


def _bootstrap(exp_config=None):
    """Creates a directory which will be used to host the development version of the experiment."""
    bootstrapper = DevelopmentDeployment(Output(), exp_config)
    log(header, chevrons=False)
    bootstrapper.run()


def launch_app_and_open_browser(port):
    _launch_app(port)
    _async_browser("dashboard", port)
    time.sleep(0.1)  # A little delay to ensure they always open in the same order
    _async_browser("ad", port)


def _launch_app(port):
    url = BASE_URL.format(port) + "launch"
    handle_launch_data(url, error=log, delay=1.0, context="local")


@develop.command()
@click.option(
    "--route",
    default=None,
    help="Route name (valid routes are: {})".format(", ".join(valid_routes.keys())),
)
@click.option("--port", default=5000, help="The port Flask is running on")
def browser(route=None, port=5000):
    _browser(route=route, port=port)


def _browser(route=None, port=5000):
    """Open one of the supported routes with appropriate path and URL parameters"""
    config = get_config(load=True)
    url_factory = valid_routes.get(route)
    if url_factory is not None:
        url = url_factory(config, port)
        log(f"Opening {route}: {url}")
        open_browser(url)
    else:
        click.echo(
            "Supported routes are:\n\t{}".format("\n\t".join(valid_routes.keys()))
        )


def _async_browser(route=None, port=5000):
    # The _browser call is pretty slow, so we run it in a thread
    # to allow us to open multiple browsers at the same time
    threading.Thread(
        target=_browser, name=f"Open {route}", kwargs={"route": route, "port": port}
    ).start()
