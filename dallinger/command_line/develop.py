import contextlib
import os
import signal
import subprocess
import threading
import time
from urllib.parse import urlparse, urlunparse

import click
from redis.exceptions import RedisError
from rq import Queue
from rq.exceptions import InvalidJobOperation
from rq.job import Job, JobStatus

from dallinger.command_line.utils import (
    Output,
    get_experiment_files,
    log,
    require_exp_directory,
)
from dallinger.config import get_config
from dallinger.db import redis_conn
from dallinger.deployment import (
    DevelopmentDeployment,
    handle_launch_data,
    stop_signals_raise_keyboard_interrupt,
)
from dallinger.utils import (
    DevelopDirectoryError,
    develop_target_path,
    ignore_stop_signals,
    open_browser,
    setup_warning_hooks,
)

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
@click.option(
    "--port",
    type=int,
    default=None,
    help="The port Flask is running on (default: the base_port setting)",
)
@click.option(
    "--skip-flask",
    is_flag=True,
    help="Skip launching Flask, so that Flask can be managed externally",
)
@click.option(
    "--no-browsers",
    is_flag=True,
    help="Skip opening browsers; log the recruitment message and dashboard login",
)
def debug(port, skip_flask, no_browsers=False):
    from dallinger.command_line.utils import verify_package

    files = get_experiment_files()
    # Skip deployable-package module verification so large experiments are not
    # copied before staging. Config loading still imports the working tree,
    # Flask imports the staged tree, and `dallinger verify` remains strict.
    if not verify_package(
        verify_experiment=False,
        experiment_files=files,
        summary=True,
    ):
        # We could instead use the @require_exp_directory decorator,
        # but this doesn't print anything useful without the verbose flag.
        # To consider for later: improving this default behavior of @require_exp_directory?
        print(
            "Cannot continue, there is a problem with the current experiment (see above)."
        )
        raise click.Abort

    _bootstrap(
        exp_config=None if port is None else {"base_port": port},
        experiment_files=files,
    )
    port = get_config().get("base_port")

    q = Queue("default", connection=redis_conn)
    if no_browsers:
        job = q.enqueue_call(launch_app_without_browsers, kwargs={"port": port})
    else:
        job = q.enqueue_call(launch_app_and_open_browser, kwargs={"port": port})

    if not skip_flask:
        try:
            develop_dir = develop_target_path(get_config())
            env = {**os.environ, "FLASK_RUN_PORT": str(port), "base_port": str(port)}
            _run_dev_server(["./run.sh"], develop_dir, env=env)
        finally:
            _cancel_pending_job(job)


def _cancel_pending_job(job):
    """Cancel ``job`` if it hasn't started, so it can't run in a later session."""
    pending = (JobStatus.QUEUED, JobStatus.DEFERRED, JobStatus.SCHEDULED)
    try:
        # A finished job's record expires, and then get_status() raises.
        if Job.exists(job.id, job.connection) and job.get_status() in pending:
            job.cancel()
    except (InvalidJobOperation, RedisError) as ex:
        log(f"Could not cancel the launch job: {ex}")


def _run_dev_server(cmd, cwd, stop_timeout=5, env=None):
    """Run the local server until it exits or this process is interrupted.

    The server runs in its own session, so Ctrl-C reaches only this process,
    which then stops the server's whole process group. SIGTERM and SIGHUP
    are treated like Ctrl-C. A SIGKILL to this process can't be passed on,
    so it leaves the server running.

    Parameters
    ----------
    cmd : list of str
        Command that starts the server.
    cwd : str
        Directory to run ``cmd`` in.
    stop_timeout : float
        Seconds to wait after SIGTERM before killing the server's processes.
    env : dict, optional
        Environment for the server; defaults to this process's environment.

    Raises
    ------
    click.ClickException
        If the server fails of its own accord.
    """
    interrupted = False
    with stop_signals_raise_keyboard_interrupt():
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, start_new_session=True)
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            interrupted = True
            log("Stopping the local server...")
        finally:
            _stop_process_group(proc, stop_timeout)
    if interrupted:
        log("Local server stopped.")
    elif code < 0:
        raise click.ClickException(
            f"The local server was killed by signal {-code}; see its output above."
        )
    elif code:
        raise click.ClickException(
            f"The local server exited with status {code}; see its output above."
        )


def _stop_process_group(proc, timeout=5):
    """Stop the process group led by ``proc`` and reap ``proc``.

    Sends SIGTERM to the group, then SIGKILL to any member still alive after
    ``timeout`` seconds. In the main thread, Ctrl-C, SIGTERM and SIGHUP are
    ignored meanwhile, so repeating them can't cut the cleanup short.
    """
    with ignore_stop_signals():
        # macOS reports EPERM for a group that only has zombies left.
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(proc.pid, signal.SIGTERM)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                proc.poll()
                os.killpg(proc.pid, 0)
                time.sleep(0.1)
            os.killpg(proc.pid, signal.SIGKILL)
        proc.wait()


@develop.command()
@require_exp_directory
def bootstrap(exp_config=None):
    _bootstrap(exp_config, experiment_files=get_experiment_files())


def _bootstrap(exp_config=None, experiment_files=None):
    """Creates a directory which will be used to host the development version of the experiment."""
    bootstrapper = DevelopmentDeployment(
        Output(),
        exp_config,
        experiment_files=experiment_files,
    )
    try:
        bootstrapper.run()
    except DevelopDirectoryError as ex:
        raise click.ClickException(str(ex))


def launch_app_and_open_browser(port):
    _launch_app(port)
    _async_browser("dashboard", port)
    time.sleep(0.1)  # A little delay to ensure they always open in the same order
    _async_browser("ad", port)


def launch_app_without_browsers(port):
    """Launch the app and log what the browsers would otherwise show.

    Matches the output of ``dallinger debug --no-browsers``.
    """
    launch_data = _launch_app(port)
    if launch_data.get("recruitment_msg"):
        log(launch_data["recruitment_msg"])
    config = get_config(load=True)
    log("Experiment dashboard: {}".format(BASE_URL.format(port) + "dashboard/develop"))
    log(
        "Dashboard user: {} password: {}".format(
            config.get("dashboard_user"),
            config.get("dashboard_password"),
        )
    )


def _launch_app(port):
    url = BASE_URL.format(port) + "launch"
    return handle_launch_data(url, error=log, delay=1.0, context="local")


@develop.command()
@click.option(
    "--route",
    default=None,
    help="Route name (valid routes are: {})".format(", ".join(valid_routes.keys())),
)
@click.option(
    "--port",
    type=int,
    default=None,
    help="The port Flask is running on (default: the base_port setting)",
)
def browser(route=None, port=None):
    if port is None:
        port = get_config(load=True).get("base_port")
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
