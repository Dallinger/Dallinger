import codecs
import json
import os
import re
import sys
import threading
import time
from shlex import quote
from urllib.parse import urlparse, urlunparse

import click
import redis
import requests
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)

from dallinger import data, db, heroku, recruiters, registration
from dallinger.config import get_config
from dallinger.heroku.tools import HerokuApp, HerokuLocalWrapper
from dallinger.redis_utils import connect_to_redis
from dallinger.utils import (
    ExperimentFileSource,
    GitClient,
    bootstrap_development_session,
    get_base_url,
    open_browser,
    print_bold,
    setup_experiment,
)

DEFAULT_DELAY = 1
BACKOFF_FACTOR = 2
MAX_ATTEMPTS = 6
STARTUP_STATUS_CODES = frozenset({502, 503, 504})
HTTPS_WAIT_MESSAGE = "Waiting for the experiment URL to become reachable"
# Status, not an error: write to stdout. Only the bar is restyled; Rich's
# default complete/pulse color is magenta-red.
_HTTPS_WAIT_BAR_STYLE = "green"


def _is_startup_exception(exc):
    """True when the launch URL is not accepting HTTPS/HTTP yet."""
    return isinstance(
        exc,
        (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.RetryError,
            requests.exceptions.ChunkedEncodingError,
        ),
    )


def _is_startup_status(status_code):
    """True for gateway statuses that mean the app is still starting."""
    try:
        return int(status_code) in STARTUP_STATUS_CODES
    except (TypeError, ValueError):
        return False


def _https_wait_progress():
    """Progress bar for the HTTPS wait. Disabled when stdout is not a TTY.

    The wait has no known length (the first POST may succeed, or we may retry
    until the timeout), so the bar is indeterminate: it pulses instead of
    sitting at 0%.
    """
    return Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(
            complete_style=_HTTPS_WAIT_BAR_STYLE,
            finished_style=_HTTPS_WAIT_BAR_STYLE,
            pulse_style=_HTTPS_WAIT_BAR_STYLE,
        ),
        TimeElapsedColumn(),
        console=Console(highlight=False),
        transient=True,
        disable=not sys.stdout.isatty(),
    )


def _announce_https_wait(announced):
    """Print a one-line wait notice on non-TTY logs; the progress bar covers TTYs."""
    if announced:
        return True
    if not sys.stdout.isatty():
        Console(highlight=False).print(HTTPS_WAIT_MESSAGE)
    return True


def handle_launch_data(
    url,
    error,
    delay=DEFAULT_DELAY,
    attempts=MAX_ATTEMPTS,
    dns_host=None,
    dozzle_password=None,
    context=None,
):
    """POST to ``url`` (``/launch``), retrying with exponential backoff.

    Connection, TLS, and gateway-startup failures are expected while the
    server becomes reachable. Those retries show a progress bar instead of
    error output. Application errors are still reported as they happen. If
    every attempt fails, the last error is reported and a
    ``click.ClickException`` summarizing the failure is raised.

    Args:
        url: The URL to send the POST request to
        error: Function to call with error messages
        delay: Initial delay between retries in seconds
        attempts: Maximum number of retry attempts
        dns_host: Hostname for Docker SSH deployments
        dozzle_password: Password for Dozzle logs in Docker SSH deployments
        context: Deployment context ('heroku', 'ssh', 'local', etc.)
    """
    launch_data = None
    launch_request = None
    last_startup_error = None
    saw_application_error = False
    announced_wait = False

    with _https_wait_progress() as progress:
        task_id = progress.add_task(HTTPS_WAIT_MESSAGE, total=None)
        for remaining_attempt in sorted(range(attempts), reverse=True):
            startup_failure = False
            try:
                launch_request = requests.post(url)
                request_happened = True
            except requests.exceptions.RequestException as err:
                request_happened = False
                if _is_startup_exception(err):
                    startup_failure = True
                    last_startup_error = f"Error accessing {url}:\n{err}"
                else:
                    saw_application_error = True
                    error(f"Error accessing {url}:\n{err}")

            if request_happened and _is_startup_status(launch_request.status_code):
                startup_failure = True
                request_happened = False
                last_startup_error = "Error accessing {} ({}):\n{}".format(
                    url, launch_request.status_code, launch_request.text
                )

            if request_happened:
                try:
                    launch_data = launch_request.json()
                except json.decoder.JSONDecodeError:
                    # Non-JSON usually means the app is not serving yet, or a
                    # real HTML error page. Treat a successful HTTP response
                    # as startup; treat error statuses as application failures.
                    request_happened = False
                    detail = (
                        f"Error parsing response from {url}, "
                        f"check server logs for details.\n{launch_request.text}"
                    )
                    if launch_request.ok:
                        startup_failure = True
                        last_startup_error = detail
                    else:
                        saw_application_error = True
                        error(detail)
                except ValueError as err:
                    error(
                        f"Error parsing response from {url}, "
                        f"check server logs for details.\n{err}\n{launch_request.text}"
                    )
                    raise

            if request_happened and launch_request.ok:
                progress.update(task_id, total=1, completed=1)
                return launch_data

            if request_happened:
                saw_application_error = True
                error(
                    "Error accessing {} ({}):\n{}".format(
                        url, launch_request.status_code, launch_request.text
                    )
                )

            if startup_failure and not saw_application_error:
                announced_wait = _announce_https_wait(announced_wait)
                attempt_number = attempts - remaining_attempt
                progress.update(
                    task_id,
                    description=(
                        f"{HTTPS_WAIT_MESSAGE} (attempt {attempt_number} of {attempts})"
                    ),
                )
            elif saw_application_error:
                progress.update(task_id, visible=False)

            if remaining_attempt:
                delay = delay * BACKOFF_FACTOR
                if not startup_failure or saw_application_error:
                    next_attempt_count = attempts - (remaining_attempt - 1)
                    error(
                        "Experiment launch failed. Trying again "
                        "(attempt {} of {}) in {} seconds ...".format(
                            next_attempt_count, attempts, delay
                        )
                    )
                time.sleep(delay)

    if not saw_application_error and last_startup_error:
        error("Timed out waiting for the experiment URL to become reachable.")
        error(last_startup_error)
        summary = (
            f"{url} never became reachable. The experiment server may still be "
            "starting up, or its TLS certificate may not have been issued yet."
        )
    else:
        error("Experiment launch failed after multiple attempts.")
        if launch_data and launch_data.get("message"):
            error(launch_data["message"])
        if launch_request is not None:
            summary = (
                f"{url} returned HTTP {launch_request.status_code}. "
                "Check the experiment server logs for details."
            )
        else:
            summary = f"Could not reach {url}."

    # Show appropriate log location message based on deployment context
    if context == "heroku":
        print_bold(
            "For detailed server logs, visit the Papertrail add-on in your Heroku dashboard"
        )
    elif context == "ssh" and dns_host and dozzle_password:
        print_bold(
            f"Check the detailed server logs at https://logs.{dns_host} (user = dallinger, password = {dozzle_password})"
        )

    # A ClickException prints as "Error: <message>" and exits non-zero, so a
    # failed launch reads as a diagnosis rather than a Python traceback.
    raise click.ClickException(f"Experiment launch failed. {summary}")


def deploy_sandbox_shared_setup(
    log,
    verbose=True,
    app=None,
    exp_config=None,
    prelaunch_actions=None,
    experiment_files=None,
):
    """Set up Git, push to Heroku, and launch the app."""
    if verbose:
        out = None
    else:
        out = open(os.devnull, "w")

    experiment_files = experiment_files or ExperimentFileSource(os.getcwd())
    config = get_config(load=True)
    heroku.sanity_check(config)
    heroku_app_id, tmp = setup_experiment(
        log,
        debug=False,
        app=app,
        exp_config=exp_config,
        local_checks=False,
        experiment_files=experiment_files,
    )

    # Register the experiment using all configured registration services.
    if config.get("mode") == "live":
        log("Registering the experiment on configured services...")
        registration.register(heroku_app_id, snapshot=None)

    # Log in to Heroku if we aren't already.
    log("Making sure that you are logged in to Heroku.")
    heroku.log_in()
    config.set("heroku_auth_token", heroku.auth_token())
    log("", chevrons=False)

    # Change to temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Commit Heroku-specific files to tmp folder's git repo.
    git = GitClient(output=out)
    git.init()
    _stage_heroku_assembly(git, experiment_files)
    git.commit('"Experiment {}"'.format(heroku_app_id))

    # Initialize the app on Heroku.
    log("Initializing app on Heroku...")
    team = config.get("heroku_team", None)
    region = config.get("heroku_region", None)
    heroku_app = HerokuApp(
        dallinger_uid=heroku_app_id, output=out, team=team, region=region
    )
    heroku_app.bootstrap()
    heroku_app.buildpack("https://github.com/stomita/heroku-buildpack-phantomjs")

    # Set up add-ons and AWS environment variables.
    database_size = config.get("database_size")
    redis_size = config.get("redis_size")
    addons = [
        "heroku-postgresql:{}".format(quote(database_size)),
        "heroku-redis:{}".format(quote(redis_size)),
        "papertrail",
    ]
    if config.get("sentry"):
        addons.append("sentry")

    for name in addons:
        heroku_app.addon(name)

    heroku_config = {
        "AWS_ACCESS_KEY_ID": config["aws_access_key_id"],
        "AWS_SECRET_ACCESS_KEY": config["aws_secret_access_key"],
        "AWS_DEFAULT_REGION": config["aws_region"],
        "auto_recruit": config["auto_recruit"],
        "smtp_username": config["smtp_username"],
        "smtp_password": config["smtp_password"],
        "whimsical": config["whimsical"],
        "FLASK_SECRET_KEY": codecs.encode(os.urandom(16), "hex").decode("ascii"),
    }

    # Set up the preferred class as an environment variable, if one is set
    # This is needed before the config is parsed, but we also store it in the
    # config to make things easier for recording into bundles.
    preferred_class = config.get("EXPERIMENT_CLASS_NAME", None)
    if preferred_class:
        heroku_config["EXPERIMENT_CLASS_NAME"] = preferred_class

    heroku_app.set_multiple(**heroku_config)

    # Wait for Redis database to be ready.
    log("Waiting for Redis (this can take a couple minutes)...", nl=False)
    ready = False
    while not ready:
        try:
            r = connect_to_redis(url=heroku_app.redis_url)
            r.set("foo", "bar")
            ready = True
            log("\n✓ connected at {}".format(heroku_app.redis_url), chevrons=False)
        except (ValueError, redis.exceptions.ConnectionError):
            time.sleep(2)
            log(".", chevrons=False, nl=False)

    log("Saving the URL of the postgres database...")
    config.extend({"database_url": heroku_app.db_url})
    config.write()
    git.add("config.txt")
    git.commit("Save URL for database")

    log("Generating dashboard links...")
    heroku_addons = heroku_app.addon_parameters()
    heroku_addons = json.dumps(heroku_addons)
    config.extend({"infrastructure_debug_details": heroku_addons})
    config.write()
    git.add("config.txt")
    git.commit("Save URLs for heroku addon management")

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    git.push(remote="heroku", branch="HEAD:master")

    log("Scaling up the dynos...")
    default_size = config.get("dyno_type")
    for process in ["web", "worker"]:
        size = config.get("dyno_type_" + process, default_size)
        qty = config.get("num_dynos_" + process)
        heroku_app.scale_up_dyno(process, qty, size)
    if config.get("clock_on"):
        heroku_app.scale_up_dyno("clock", 1, size)

    if prelaunch_actions is not None:
        for task in prelaunch_actions:
            task(heroku_app, config)

    # Launch the experiment.
    log("Launching the experiment on the remote server and starting recruitment...")
    launch_url = "{}/launch".format(heroku_app.url)
    log("Calling {}".format(launch_url), chevrons=False)
    launch_data = handle_launch_data(launch_url, error=log)
    result = {
        "app_name": heroku_app.name,
        "app_home": heroku_app.url,
        "dashboard_url": "{}/dashboard/".format(heroku_app.url),
        "dashboard_user": config.get("dashboard_user"),
        "dashboard_password": config.get("dashboard_password"),
        "recruitment_msg": launch_data.get("recruitment_msg", None),
    }

    log("Experiment details:")
    log("App home: {}".format(result["app_home"]), chevrons=False)
    log("Dashboard URL: {}".format(result["dashboard_url"]), chevrons=False)
    log("Dashboard user: {}".format(config.get("dashboard_user")), chevrons=False)
    log(
        "Dashboard password: {}".format(config.get("dashboard_password")),
        chevrons=False,
    )

    log("Recruiter info:")
    log(result["recruitment_msg"], chevrons=False)

    # Return to the branch whence we came.
    os.chdir(cwd)

    log(
        "Completed Heroku deployment of experiment ID {} using app ID {}.".format(
            config.get("id"), heroku_app_id
        )
    )
    return result


def _stage_heroku_assembly(git, experiment_files):
    """Stage a Heroku assembly without changing legacy ignore behavior."""
    if experiment_files.deployment_plan is None:
        git.add("--all")
    else:
        git.add("--force", "--all")


class DevelopmentDeployment:
    """Collates files from Dallinger and the custom experment, then symlinks
    them into a target sub-directory, so Flask development server can be run
    manually in that directory.
    """

    def __init__(
        self,
        output,
        exp_config,
        experiment_files=None,
    ):
        self.out = output
        self.exp_config = exp_config or {}
        self.exp_config.update({"mode": "debug"})
        self.experiment_files = experiment_files

    def run(self):
        """Bootstrap the environment and reset the database."""
        experiment_uid, dst = bootstrap_development_session(
            self.exp_config,
            os.getcwd(),
            self.out.log,
            experiment_files=self.experiment_files,
        )
        db.init_db(drop_all=True)


class HerokuLocalDeployment:
    exp_id = None
    tmp_dir = None
    dispatch = {}  # Subclass may provide handlers for Heroku process output
    environ = None
    bot = False
    experiment_files = None
    DEPLOY_NAME = "Heroku"
    WRAPPER_CLASS = HerokuLocalWrapper
    DO_INIT_DB = True

    def configure(self):
        self.exp_config.update({"mode": "debug"})

    def setup(self):
        source = self.experiment_files or ExperimentFileSource(os.getcwd())
        self.exp_id, self.tmp_dir = setup_experiment(
            self.out.log,
            exp_config=self.exp_config,
            experiment_files=source,
        )

    def update_dir(self):
        # FIXME: this call is used for implicit communication between classes in this file
        # and service wrappers (HerokuLocalWrapper, DockerComposeWrapper).
        # This communication should be made explicit, passing this path around instead of
        # changing a global state.
        os.chdir(self.tmp_dir)
        # Update the logfile to the new directory
        config = get_config(load=True)
        logfile = config.get("logfile")
        if logfile and logfile != "-":
            logfile = os.path.join(self.original_dir, logfile)
            config.extend({"logfile": logfile})
        config.write()

    def run(self):
        """Set up the environment, get a wrapper instance, and pass
        it to the concrete class's execute() method.
        """
        self.configure()
        self.setup()
        self.update_dir()
        if self.DO_INIT_DB:
            db.init_db(drop_all=True)
        config = get_config()
        environ = None
        if self.environ:
            environ = os.environ.copy()
            environ.update(self.environ)
        self.out.log(f"Starting up the {self.DEPLOY_NAME} Local server...")
        with self.WRAPPER_CLASS(
            config,
            self.out,
            self.original_dir,
            self.tmp_dir,
            verbose=self.verbose,
            env=environ,
            needs_chrome=self.bot,
        ) as wrapper:
            try:
                self.execute(wrapper)
            except KeyboardInterrupt:
                pass
            finally:
                os.chdir(self.original_dir)
                self.cleanup()

    def notify(self, message):
        """Callback function which checks lines of output, tries to match
        against regex defined in subclass's "dispatch" dict, and passes through
        to a handler on match.
        """
        for regex, handler in self.dispatch.items():
            match = re.search(regex, message)
            if match:
                handler = getattr(self, handler)
                return handler(match)

    def execute(self, heroku):
        raise NotImplementedError()


class DebugDeployment(HerokuLocalDeployment):
    dispatch = {
        r"[^\"]{} (.*)$".format(recruiters.NEW_RECRUIT_LOG_PREFIX): "new_recruit",
        r"{}".format(recruiters.CLOSE_RECRUITMENT_LOG_PREFIX): "recruitment_closed",
    }

    def __init__(
        self,
        output,
        verbose,
        bot,
        proxy_port,
        exp_config,
        no_browsers=False,
        experiment_files=None,
    ):
        self.out = output
        self.verbose = verbose
        self.bot = bot
        self.exp_config = exp_config or {}
        self.proxy_port = proxy_port
        self.original_dir = os.getcwd()
        self.complete = False
        self.status_thread = None
        self.no_browsers = no_browsers
        self.experiment_files = experiment_files
        self.environ = {
            "FLASK_SECRET_KEY": codecs.encode(os.urandom(16), "hex").decode("ascii"),
        }

    def with_proxy_port(self, url):
        if self.proxy_port is not None:
            self.out.log("Using proxy port {}".format(self.proxy_port))
            url = url.replace(str(get_config().get("base_port")), self.proxy_port)
        return url

    def configure(self):
        super(DebugDeployment, self).configure()
        if self.bot:
            self.exp_config["recruiter"] = "bots"

    def execute(self, heroku):
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))
        self.out.log("Launching the experiment...")
        try:
            result = handle_launch_data(
                "{}/launch".format(base_url), error=self.out.error, attempts=1
            )
        except Exception:
            # Show output from server
            self.dispatch[r"POST /launch"] = "launch_request_complete"
            heroku.monitor(listener=self.notify)
        else:
            if result["status"] == "success":
                self.out.log(result["recruitment_msg"])
                dashboard_url = self.with_proxy_port("{}/dashboard/".format(base_url))
                self.display_dashboard_access_details(dashboard_url)
                if not self.no_browsers:
                    self.async_open_dashboard(dashboard_url)

                # A little delay here ensures that the experiment window always opens
                # after the dashboard window.
                time.sleep(0.1)

                self.heroku = heroku
                self.out.log(
                    "Monitoring the Heroku Local server for recruitment or completion..."
                )
                heroku.monitor(listener=self.notify)

    def launch_request_complete(self, match):
        return HerokuLocalWrapper.MONITOR_STOP

    def cleanup(self):
        self.out.log("Completed debugging of experiment with id " + self.exp_id)
        self.complete = True

    def new_recruit(self, match):
        """Dispatched to by notify(). If a recruitment request has been issued,
        open a browser window for the a new participant (in this case the
        person doing local debugging).
        """
        self.out.log("new recruitment request!")
        if self.no_browsers:
            self.out.log(recruiters.NEW_RECRUIT_LOG_PREFIX + ": " + match.group(1))
            return
        url = self.with_proxy_port(match.group(1))

        open_browser(url)

    def display_dashboard_access_details(self, url):
        config = get_config()
        self.out.log("Experiment dashboard: {}".format(url))
        self.out.log(
            "Dashboard user: {} password: {}".format(
                config.get("dashboard_user"),
                config.get("dashboard_password"),
            )
        )

    def async_open_dashboard(self, url):
        threading.Thread(
            target=self.open_dashboard, name="Open dashboard", kwargs={"url": url}
        ).start()

    def open_dashboard(self, url):
        config = get_config()
        self.out.log("Opening dashboard")
        parsed = list(urlparse(url))
        parsed[1] = "{}:{}@{}".format(
            config.get("dashboard_user"),
            config.get("dashboard_password"),
            parsed[1],
        )
        open_browser(urlunparse(parsed))

    def recruitment_closed(self, match):
        """Recruitment is closed.

        Start a thread to check the experiment summary.
        """
        if self.no_browsers:
            self.out.log(recruiters.CLOSE_RECRUITMENT_LOG_PREFIX)
        if self.status_thread is None:
            self.status_thread = threading.Thread(target=self.check_status)
            self.status_thread.start()

    def check_status(self):
        """Check the output of the summary route until
        the experiment is complete, then we can stop monitoring Heroku
        subprocess output.
        """
        self.out.log("Recruitment is complete. Waiting for experiment completion...")
        base_url = get_base_url()
        status_url = base_url + "/summary"
        while not self.complete:
            time.sleep(10)
            try:
                resp = requests.get(status_url)
                exp_data = resp.json()
            except (ValueError, requests.exceptions.RequestException):
                self.out.error("Error fetching experiment status.")
            else:
                self.out.log("Experiment summary: {}".format(exp_data))
                if exp_data.get("completed", False):
                    self.out.log("Experiment completed, all nodes filled.")
                    self.complete = True
                    self.heroku.stop()

    def notify(self, message):
        """Monitor output from heroku process.

        This overrides the base class's `notify`
        to make sure that we stop if the status-monitoring thread
        has determined that the experiment is complete.
        """
        if self.complete:
            return HerokuLocalWrapper.MONITOR_STOP
        return super(DebugDeployment, self).notify(message)


class LoaderDeployment(HerokuLocalDeployment):
    dispatch = {"Replay ready: (.*)$": "start_replay"}

    def __init__(self, app_id, output, verbose, exp_config, experiment_files=None):
        self.app_id = app_id
        self.out = output
        self.verbose = verbose
        self.exp_config = exp_config or {}
        self.original_dir = os.getcwd()
        self.zip_path = None
        self.experiment_files = experiment_files

    def configure(self):
        self.exp_config.update({"mode": "debug", "loglevel": 0})

        self.zip_path = data.find_experiment_export(self.app_id)
        if self.zip_path is None:
            msg = 'Dataset export for app id "{}" could not be found.'
            raise IOError(msg.format(self.app_id))

    def setup(self):
        source = self.experiment_files or ExperimentFileSource(os.getcwd())
        self.exp_id, self.tmp_dir = setup_experiment(
            self.out.log,
            app=self.app_id,
            exp_config=self.exp_config,
            experiment_files=source,
        )

    def execute(self, heroku):
        """Start the server, load the zip file into the database, then loop
        until terminated with <control>-c.
        """
        db.init_db(drop_all=True)
        self.out.log(
            "Ingesting dataset from {}...".format(os.path.basename(self.zip_path))
        )
        data.ingest_zip(self.zip_path)
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))

        if self.exp_config.get("replay"):
            self.out.log("Launching the experiment...")
            time.sleep(4)
            handle_launch_data("{}/launch".format(base_url), error=self.out.error)
            heroku.monitor(listener=self.notify)

        # Just run until interrupted:
        while self.keep_running():
            time.sleep(1)

    def start_replay(self, match):
        """Dispatched to by notify(). If a recruitment request has been issued,
        open a browser window for the a new participant (in this case the
        person doing local debugging).
        """
        self.out.log("replay ready!")
        url = match.group(1)
        open_browser(url)

    def cleanup(self):
        self.out.log("Terminating dataset load for experiment {}".format(self.exp_id))

    def keep_running(self):
        # This is a separate method so that it can be replaced in tests
        return True
