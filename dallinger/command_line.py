#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Dallinger command-line utility."""

import imp
import inspect
import os
import pkg_resources
import re
try:
    from pipes import quote
except ImportError:
    # Python >= 3.3
    from shlex import quote
import shutil
import sys
import tempfile
import time
import webbrowser

from functools import wraps
import signal
import click
from dallinger.config import get_config
import psycopg2
import redis
import requests
from rq import (
    Worker,
    Connection,
)
from collections import Counter

from dallinger import data
from dallinger import db
from dallinger import heroku
from dallinger.heroku.messages import EmailingHITMessager
from dallinger.heroku.worker import conn
from dallinger.heroku.tools import HerokuLocalWrapper
from dallinger.heroku.tools import HerokuApp
from dallinger.mturk import MTurkService
from dallinger import recruiters
from dallinger import registration
from dallinger.utils import check_call
from dallinger.utils import generate_random_id
from dallinger.utils import get_base_url
from dallinger.utils import GitClient
from dallinger.version import __version__

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

header = """
    ____        ____
   / __ \____ _/ / (_)___  ____ ____  _____
  / / / / __ `/ / / / __ \/ __ `/ _ \/ ___/
 / /_/ / /_/ / / / / / / / /_/ /  __/ /
/_____/\__,_/_/_/_/_/ /_/\__, /\___/_/
                        /____/
                                 {:>8}

                Laboratory automation for
       the behavioral and social sciences.
""".format("v" + __version__)


def log(msg, delay=0.5, chevrons=True, verbose=True):
    """Log a message to stdout."""
    if verbose:
        if chevrons:
            click.echo(u"\n❯❯ " + msg)
        else:
            click.echo(msg)
        time.sleep(delay)


def error(msg, delay=0.5, chevrons=True, verbose=True):
    """Log a message to stdout."""
    if verbose:
        if chevrons:
            click.secho(u"\n❯❯ " + msg, err=True, fg='red')
        else:
            click.secho(msg, err=True, fg='red')
        time.sleep(delay)


def report_idle_after(seconds):
    """Report_idle_after after certain number of seconds."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            def _handle_timeout(signum, frame):
                try:
                    config = get_config()
                    config.load()
                    heroku_config = {
                        "contact_email_on_error": config["contact_email_on_error"],
                        "dallinger_email_username": config["dallinger_email_address"],
                        "dallinger_email_key": config["dallinger_email_password"],
                        "whimsical": False
                    }
                    app_id = config["id"]
                    email = EmailingHITMessager(when=time, assignment_id=None,
                                                hit_duration=seconds, time_active=seconds,
                                                config=heroku_config, app_id=app_id)
                    log("Sending email...")
                    email.send_idle_experiment()
                except KeyError:
                    log("Config keys not set to send emails...")

            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(seconds)
            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
            return result

        return wraps(func)(wrapper)

    return decorator


def verify_id(ctx, param, app):
    """Verify the experiment id."""
    if app is None:
        raise TypeError("Select an experiment using the --app flag.")
    elif app[0:5] == "dlgr-":
        raise ValueError("The --app flag requires the full "
                         "UUID beginning with {}-...".format(app[5:13]))
    return app


def verify_package(verbose=True):
    """Ensure the package has a config file and a valid experiment file."""
    is_passing = True

    # Check for existence of required files.
    required_files = [
        "config.txt",
        "experiment.py",
    ]

    for f in required_files:
        if os.path.exists(f):
            log("✓ {} is PRESENT".format(f), chevrons=False, verbose=verbose)
        else:
            log("✗ {} is MISSING".format(f), chevrons=False, verbose=verbose)
            is_passing = False

    # Check the experiment file.
    if os.path.exists("experiment.py"):

        # Check if the experiment file has exactly one Experiment class.
        tmp = tempfile.mkdtemp()
        clone_dir = os.path.join(tmp, 'temp_exp_pacakge')
        to_ignore = shutil.ignore_patterns(
            os.path.join(".git", "*"),
            "*.db",
            "snapshots",
            "data",
            "server.log"
        )
        shutil.copytree(os.getcwd(), clone_dir, ignore=to_ignore)

        cwd = os.getcwd()
        os.chdir(clone_dir)
        sys.path.append(clone_dir)

        exp = imp.load_source('experiment', os.path.join(clone_dir, "experiment.py"))

        classes = inspect.getmembers(exp, inspect.isclass)
        exps = [c for c in classes
                if (c[1].__bases__[0].__name__ in "Experiment")]

        if len(exps) == 0:
            log("✗ experiment.py does not define an experiment class.",
                delay=0, chevrons=False, verbose=verbose)
            is_passing = False
        elif len(exps) == 1:
            log("✓ experiment.py defines 1 experiment",
                delay=0, chevrons=False, verbose=verbose)
        else:
            log("✗ experiment.py defines more than one experiment class.",
                delay=0, chevrons=False, verbose=verbose)
        os.chdir(cwd)
        sys.path.remove(clone_dir)

    config = get_config()
    if not config.ready:
        config.load()

    # Check base_payment is correct
    base_pay = config.get('base_payment')
    dollarFormat = "{:.2f}".format(base_pay)

    if base_pay <= 0:
        log("✗ base_payment must be positive value in config.txt.",
            delay=0, chevrons=False, verbose=verbose)
        is_passing = False

    if float(dollarFormat) != float(base_pay):
        log("✗ base_payment must be in [dollars].[cents] format in config.txt. Try changing "
            "{0} to {1}.".format(base_pay, dollarFormat), delay=0, chevrons=False, verbose=verbose)
        is_passing = False

    # Check front-end files do not exist
    files = [
        os.path.join("templates", "complete.html"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "thanks.html"),
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "scripts", "dallinger.js"),
        os.path.join("static", "scripts", "dallinger2.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "robots.txt")
    ]

    for f in files:
        if os.path.exists(f):
            log("✗ {} OVERWRITES shared frontend files inserted at run-time".format(f),
                delay=0, chevrons=False, verbose=verbose)

    log("✓ no file conflicts", delay=0, chevrons=False, verbose=verbose)

    return is_passing


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, '--version', '-v', message='%(version)s')
def dallinger():
    """Dallinger command-line utility."""
    from logging.config import fileConfig
    fileConfig(os.path.join(os.path.dirname(__file__), 'logging.ini'),
               disable_existing_loggers=False)


@dallinger.command()
def setup():
    """Walk the user though the Dallinger setup."""
    # Create the Dallinger config file if it does not already exist.
    config_name = ".dallingerconfig"
    config_path = os.path.join(os.path.expanduser("~"), config_name)

    if os.path.isfile(config_path):
        log("Dallinger config file already exists.", chevrons=False)

    else:
        log("Creating Dallinger config file at ~/.dallingerconfig...",
            chevrons=False)
        src = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "default_configs",
            config_name
        )
        shutil.copyfile(src, config_path)


def setup_experiment(debug=True, verbose=False, app=None, exp_config=None):
    """Check the app and, if compatible with Dallinger, freeze its state."""
    log(header, chevrons=False)

    # Verify that the Postgres server is running.
    try:
        psycopg2.connect(database="x", user="postgres", password="nada")
    except psycopg2.OperationalError as e:
        if "could not connect to server" in str(e):
            raise RuntimeError("The Postgres server isn't running.")

    # Load configuration.
    config = get_config()
    if not config.ready:
        config.load()

    # Check that the demo-specific requirements are satisfied.
    try:
        with open("requirements.txt", "r") as f:
            dependencies = [r for r in f.readlines() if r[:3] != "-e "]
    except (OSError, IOError):
        dependencies = []

    pkg_resources.require(dependencies)

    # Generate a unique id for this experiment.
    from dallinger.experiment import Experiment
    generated_uid = public_id = Experiment.make_uuid()

    # If the user provided an app name, use it everywhere that's user-facing.
    if app:
        public_id = str(app)

    log("Experiment id is " + public_id + "")

    # Copy this directory into a temporary folder, ignoring .git
    dst = os.path.join(tempfile.mkdtemp(), public_id)
    to_ignore = shutil.ignore_patterns(
        os.path.join(".git", "*"),
        "*.db",
        "snapshots",
        "data",
        "server.log"
    )
    shutil.copytree(os.getcwd(), dst, ignore=to_ignore)

    click.echo(dst)

    # Save the experiment id
    with open(os.path.join(dst, "experiment_id.txt"), "w") as file:
        file.write(generated_uid)

    # Change directory to the temporary folder.
    cwd = os.getcwd()
    os.chdir(dst)

    # Write the custom config
    if exp_config:
        config.extend(exp_config)

    config.extend({'id': unicode(generated_uid)})

    config.write(filter_sensitive=True)

    # Zip up the temporary directory and place it in the cwd.
    if not debug:
        log("Freezing the experiment package...")
        shutil.make_archive(
            os.path.join(cwd, "snapshots", public_id + "-code"), "zip", dst)

    # Check directories.
    if not os.path.exists(os.path.join("static", "scripts")):
        os.makedirs(os.path.join("static", "scripts"))
    if not os.path.exists("templates"):
        os.makedirs("templates")
    if not os.path.exists(os.path.join("static", "css")):
        os.makedirs(os.path.join("static", "css"))

    # Rename experiment.py for backwards compatibility.
    os.rename(
        os.path.join(dst, "experiment.py"),
        os.path.join(dst, "dallinger_experiment.py"))

    # Get dallinger package location.
    from pkg_resources import get_distribution
    dist = get_distribution('dallinger')
    src_base = os.path.join(dist.location, dist.project_name)

    heroku_files = [
        "Procfile",
        "launch.py",
        "worker.py",
        "clock.py",
        "runtime.txt",
    ]

    for filename in heroku_files:
        src = os.path.join(src_base, "heroku", filename)
        shutil.copy(src, os.path.join(dst, filename))

    clock_on = config.get('clock_on', False)

    # If the clock process has been disabled, overwrite the Procfile.
    if not clock_on:
        src = os.path.join(src_base, "heroku", "Procfile_no_clock")
        shutil.copy(src, os.path.join(dst, "Procfile"))

    frontend_files = [
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "scripts", "dallinger.js"),
        os.path.join("static", "scripts", "dallinger2.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "scripts", "reconnecting-websocket.js"),
        os.path.join("static", "scripts", "spin.min.js"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "complete.html"),
        os.path.join("templates", "questionnaire.html"),
        os.path.join("templates", "thanks.html"),
        os.path.join("templates", "waiting.html"),
        os.path.join("static", "robots.txt")
    ]
    frontend_dirs = [
        os.path.join("templates", "base"),
    ]

    for filename in frontend_files:
        src = os.path.join(src_base, "frontend", filename)
        dst_filepath = os.path.join(dst, filename)
        if not os.path.exists(dst_filepath):
            shutil.copy(src, dst_filepath)
    for filename in frontend_dirs:
        src = os.path.join(src_base, "frontend", filename)
        dst_filepath = os.path.join(dst, filename)
        if not os.path.exists(dst_filepath):
            shutil.copytree(src, dst_filepath)

    time.sleep(0.25)

    os.chdir(cwd)

    return (public_id, dst)


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
def summary(app):
    """Print a summary of a deployed app's status."""
    click.echo(get_summary(app))


@dallinger.command()
def uuid():
    """Print a new UUID"""
    from dallinger.experiment import Experiment
    click.echo(Experiment.make_uuid())


def get_summary(app):
    heroku_app = HerokuApp(app)
    r = requests.get('{}/summary'.format(heroku_app.url))
    summary = r.json()['summary']
    out = []
    out.append("\nstatus    | count")
    out.append("----------------")
    for s in summary:
        out.append("{:<10}| {}".format(s[0], s[1]))
    num_approved = sum([s[1] for s in summary if s[0] == u"approved"])
    num_not_working = sum([s[1] for s in summary if s[0] != u"working"])
    if num_not_working > 0:
        the_yield = 1.0 * num_approved / num_not_working
        out.append("\nYield: {:.2%}".format(the_yield))
    return "\n".join(out)


def _handle_launch_data(url, error=error):
    launch_request = requests.post(url)
    try:
        launch_data = launch_request.json()
    except ValueError:
        error(
            u"Error parsing response from /launch, check web dyno logs for details: "
            + launch_request.text
        )
        raise

    if not launch_request.ok:
        error('Experiment launch failed, check web dyno logs for details.')
        if launch_data.get('message'):
            error(launch_data['message'])
        launch_request.raise_for_status()
    return launch_data


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--bot', is_flag=True, flag_value=True,
              help='Use bot to complete experiment')
@click.option('--proxy', default=None, help='Alternate port when opening browser windows')
def debug(verbose, bot, proxy, exp_config=None):
    """Run the experiment locally."""
    debugger = DebugSessionRunner(Output(), verbose, bot, proxy, exp_config)
    debugger.run()


def deploy_sandbox_shared_setup(verbose=True, app=None, exp_config=None):
    """Set up Git, push to Heroku, and launch the app."""
    if verbose:
        out = None
    else:
        out = open(os.devnull, 'w')

    (id, tmp) = setup_experiment(debug=False, verbose=verbose, app=app,
                                 exp_config=exp_config)

    config = get_config()  # We know it's ready; setup_experiment() does this.

    # Register the experiment using all configured registration services.
    if config.get("mode") == u"live":
        log("Registering the experiment on configured services...")
        registration.register(id, snapshot=None)

    # Log in to Heroku if we aren't already.
    log("Making sure that you are logged in to Heroku.")
    heroku.log_in()
    config.set("heroku_auth_token", heroku.auth_token())
    click.echo("")

    # Change to temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Commit Heroku-specific files to tmp folder's git repo.
    git = GitClient(output=out)
    git.init()
    git.add("--all")
    git.commit('"Experiment {}"'.format(id))

    # Initialize the app on Heroku.
    log("Initializing app on Heroku...")
    team = config.get("heroku_team", '').strip() or None
    heroku_app = HerokuApp(dallinger_uid=id, output=out, team=team)
    heroku_app.bootstrap()
    heroku_app.buildpack("https://github.com/stomita/heroku-buildpack-phantomjs")

    # Set up add-ons and AWS environment variables.
    database_size = config.get('database_size')
    addons = [
        "heroku-postgresql:{}".format(quote(database_size)),
        "heroku-redis:premium-0",
        "papertrail"
    ]
    if config.get("sentry", False):
        addons.append("sentry")

    for name in addons:
        heroku_app.addon(name)

    heroku_config = {
        "aws_access_key_id": config["aws_access_key_id"],
        "aws_secret_access_key": config["aws_secret_access_key"],
        "aws_region": config["aws_region"],
        "auto_recruit": config["auto_recruit"],
        "dallinger_email_username": config["dallinger_email_address"],
        "dallinger_email_key": config["dallinger_email_password"],
        "whimsical": config["whimsical"],
    }

    for k, v in sorted(heroku_config.items()):  # sorted for testablility
        heroku_app.set(k, v)

    # Wait for Redis database to be ready.
    log("Waiting for Redis...")
    ready = False
    while not ready:
        r = redis.from_url(heroku_app.redis_url)
        try:
            r.set("foo", "bar")
            ready = True
        except redis.exceptions.ConnectionError:
            time.sleep(2)

    log("Saving the URL of the postgres database...")
    # Set the notification URL and database URL in the config file.
    config.extend({
        "notification_url": heroku_app.url + u"/notifications",
        "database_url": heroku_app.db_url,
    })
    config.write()
    git.add("config.txt")
    time.sleep(0.25)
    git.commit("Save URLs for database and notifications")
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    git.push(remote="heroku", branch="HEAD:master")

    log("Scaling up the dynos...")
    size = config.get("dyno_type")
    for process in ["web", "worker"]:
        qty = config.get("num_dynos_" + process)
        heroku_app.scale_up_dyno(process, qty, size)
    if config.get("clock_on"):
        heroku_app.scale_up_dyno("clock", 1, size)

    time.sleep(8)

    # Launch the experiment.
    log("Launching the experiment on the remote server and starting recruitment...")
    launch_data = _handle_launch_data('{}/launch'.format(heroku_app.url))
    result = {
        'app_name': heroku_app.name,
        'app_home': heroku_app.url,
        'recruitment_msg': launch_data.get('recruitment_msg', None),
    }
    log("Experiment details:")
    log("App home: {}".format(result['app_home']), chevrons=False)
    log("Recruiter info:")
    log(result['recruitment_msg'], chevrons=False)

    # Return to the branch whence we came.
    os.chdir(cwd)

    log("Completed deployment of experiment " + id + ".")
    return result


def _deploy_in_mode(mode, app, verbose):
    # Load configuration.
    if app:
        verify_id(None, None, app)

    config = get_config()
    config.load()

    # Set the mode.
    config.extend({
        "mode": mode,
        "logfile": u"-",
    })

    # Do shared setup.
    deploy_sandbox_shared_setup(verbose=verbose, app=app)


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='Experiment id')
@report_idle_after(21600)
def sandbox(verbose, app):
    """Deploy app using Heroku to the MTurk Sandbox."""
    _deploy_in_mode(u'sandbox', app, verbose)


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='ID of the deployed experiment')
@report_idle_after(21600)
def deploy(verbose, app):
    """Deploy app using Heroku to MTurk."""
    _deploy_in_mode(u'live', app, verbose)


@dallinger.command()
@click.option('--qualification')
@click.option('--value')
@click.option('--by_name', is_flag=True, flag_value=True,
              help='Use a qualification name, not an ID')
@click.option('--notify', is_flag=True, flag_value=True, help='Notify worker by email')
@click.option('--sandbox', is_flag=True, flag_value=True, help='Use the MTurk sandbox')
@click.argument('workers', nargs=-1)
def qualify(workers, qualification, value, by_name, notify, sandbox):
    """Assign a qualification to 1 or more workers"""
    if not (workers and qualification and value):
        raise click.BadParameter(
            'Must specify a qualification ID, value/score, and at least one worker ID'
        )

    config = get_config()
    config.load()
    mturk = MTurkService(
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key'),
        sandbox=sandbox,
    )
    if by_name:
        result = mturk.get_qualification_type_by_name(qualification)
        if result is None:
            raise click.BadParameter(
                'No qualification with name "{}" exists.'.format(qualification))

        qid = result['id']
    else:
        qid = qualification

    click.echo(
        "Assigning qualification {} with value {} to {} worker{}...".format(
            qid,
            value,
            len(workers),
            's' if len(workers) > 1 else '')
    )
    for worker in workers:
        if mturk.set_qualification_score(qid, worker, value, notify=notify):
            click.echo('{} OK'.format(worker))

    # print out the current set of workers with the qualification
    results = list(mturk.get_workers_with_qualification(qid))

    click.echo("{} workers with qualification {}:".format(
        len(results),
        qid))

    for score, count in Counter([r['score'] for r in results]).items():
        click.echo("{} with value {}".format(count, score))


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
def hibernate(app):
    """Pause an experiment and remove costly resources."""
    log("The database backup URL is...")
    backup_url = data.backup(app)
    log(backup_url)

    log("Scaling down the web servers...")
    heroku_app = HerokuApp(app)
    for process in ["web", "worker", "clock"]:
        heroku_app.scale_down_dyno(process)

    log("Removing addons...")

    addons = [
        "heroku-postgresql",
        # "papertrail",
        "heroku-redis",
    ]
    for addon in addons:
        heroku_app.addon_destroy(addon)


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.confirmation_option(prompt='Are you sure you want to destroy the app?')
def destroy(app):
    """Tear down an experiment server."""
    HerokuApp(app).destroy()


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.option('--databaseurl', default=None, help='URL of the database')
def awaken(app, databaseurl):
    """Restore the database from a given url."""
    id = app
    config = get_config()
    config.load()

    bucket = data.user_s3_bucket()
    key = bucket.lookup('{}.dump'.format(id))
    url = key.generate_url(expires_in=300)

    heroku_app = HerokuApp(id, output=None, team=None)
    heroku_app.addon("heroku-postgresql:{}".format(config.get('database_size')))
    time.sleep(60)

    heroku_app.pg_wait()
    time.sleep(10)

    heroku_app.addon("heroku-redis:premium-0")
    heroku_app.restore(url)

    # Scale up the dynos.
    log("Scaling up the dynos...")
    size = config.get("dyno_type")
    for process in ["web", "worker"]:
        qty = config.get("num_dynos_" + process)
        heroku_app.scale_up_dyno(process, qty, size)
    if config.get("clock_on"):
        heroku_app.scale_up_dyno("clock", 1, size)


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.option('--local', is_flag=True, flag_value=True,
              help='Export local data')
@click.option('--no-scrub', is_flag=True, flag_value=True,
              help='Scrub PII')
def export(app, local, no_scrub):
    """Export the data."""
    log(header, chevrons=False)
    data.export(str(app), local=local, scrub_pii=(not no_scrub))


class Output(object):

    def __init__(self, log=log, error=error, blather=sys.stdout.write):
        self.log = log
        self.error = error
        self.blather = sys.stdout.write


class LocalSessionRunner(object):

    exp_id = None
    tmp_dir = None
    dispatch = {}  # Subclass may provide handlers for Heroku process output

    def configure(self):
        self.exp_config.update({
            "mode": u"debug",
            "loglevel": 0,
        })

    def setup(self):
        self.exp_id, self.tmp_dir = setup_experiment(
            verbose=self.verbose, exp_config=self.exp_config)

    def update_dir(self):
        os.chdir(self.tmp_dir)
        # Update the logfile to the new directory
        config = get_config()
        logfile = config.get('logfile')
        if logfile and logfile != '-':
            logfile = os.path.join(self.original_dir, logfile)
            config.extend({'logfile': logfile})
            config.write()

    def run(self):
        """Set up the environment, get a HerokuLocalWrapper instance, and pass
        it to the concrete class's execute() method.
        """
        self.configure()
        self.setup()
        self.update_dir()
        db.init_db(drop_all=True)
        self.out.log("Starting up the server...")
        config = get_config()
        with HerokuLocalWrapper(config, self.out, verbose=self.verbose) as wrapper:
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


class DebugSessionRunner(LocalSessionRunner):

    dispatch = {
        r'[^\"]{} (.*)$'.format(recruiters.NEW_RECRUIT_LOG_PREFIX): 'new_recruit',
        r'{}$'.format(recruiters.CLOSE_RECRUITMENT_LOG_PREFIX): 'recruitment_closed',
    }

    def __init__(self, output, verbose, bot, proxy_port, exp_config):
        self.out = output
        self.verbose = verbose
        self.bot = bot
        self.exp_config = exp_config or {}
        self.proxy_port = proxy_port
        self.original_dir = os.getcwd()

    def configure(self):
        super(DebugSessionRunner, self).configure()
        if self.bot:
            self.exp_config["recruiter"] = u"bots"

    def execute(self, heroku):
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))
        self.out.log("Launching the experiment...")
        time.sleep(4)
        result = _handle_launch_data('{}/launch'.format(base_url), error=self.out.error)
        if result['status'] == 'success':
            self.out.log(result['recruitment_msg'])
            heroku.monitor(listener=self.notify)

    def cleanup(self):
        log("Completed debugging of experiment with id " + self.exp_id)

    def new_recruit(self, match):
        """Dispatched to by notify(). If a recruitment request has been issued,
        open a browser window for the a new participant (in this case the
        person doing local debugging).
        """
        self.out.log("new recruitment request!")
        url = match.group(1)
        if self.proxy_port is not None:
            self.out.log("Using proxy port {}".format(self.proxy_port))
            url = url.replace(str(get_config().get('base_port')), self.proxy_port)
        webbrowser.open(url, new=1, autoraise=True)

    def recruitment_closed(self, match):
        """Recruitment is closed. Check the output of the summary route until
        the experiment is complete, then we can stop monitoring Heroku
        subprocess output.
        """
        base_url = get_base_url()
        status_url = base_url + '/summary'
        self.out.log("Recruitment is complete. Waiting for experiment completion...")
        time.sleep(10)
        try:
            resp = requests.get(status_url)
            exp_data = resp.json()
        except (ValueError, requests.exceptions.RequestException):
            self.out.error('Error fetching experiment status.')
        self.out.log('Experiment summary: {}'.format(exp_data))
        if exp_data.get('completed', False):
            self.out.log('Experiment completed, all nodes filled.')
            return HerokuLocalWrapper.MONITOR_STOP


class LoadSessionRunner(LocalSessionRunner):
    dispatch = {
        'Replay ready: (.*)$': 'start_replay',
    }

    def __init__(self, app_id, output, verbose, exp_config):
        self.app_id = app_id
        self.out = output
        self.verbose = verbose
        self.exp_config = exp_config or {}
        self.original_dir = os.getcwd()
        self.zip_path = None

    def configure(self):
        self.exp_config.update({
            "mode": u"debug",
            "loglevel": 0,
        })

        self.zip_path = data.find_experiment_export(self.app_id)
        if self.zip_path is None:
            msg = u'Dataset export for app id "{}" could not be found.'
            raise IOError(msg.format(self.app_id))

    def setup(self):
        self.exp_id, self.tmp_dir = setup_experiment(
            app=self.app_id, verbose=self.verbose, exp_config=self.exp_config)

    def execute(self, heroku):
        """Start the server, load the zip file into the database, then loop
        until terminated with <control>-c.
        """
        db.init_db(drop_all=True)
        self.out.log("Ingesting dataset from {}...".format(os.path.basename(self.zip_path)))
        data.ingest_zip(self.zip_path)
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))

        if self.exp_config.get('replay', False):
            self.out.log("Launching the experiment...")
            time.sleep(4)
            _handle_launch_data('{}/launch'.format(base_url), error=self.out.error)
            heroku.monitor(listener=self.notify)

        # Just run until interrupted:
        while(self.keep_running()):
            time.sleep(1)

    def start_replay(self, match):
        """Dispatched to by notify(). If a recruitment request has been issued,
        open a browser window for the a new participant (in this case the
        person doing local debugging).
        """
        self.out.log("replay ready!")
        url = match.group(1)
        webbrowser.open(url, new=1, autoraise=True)

    def cleanup(self):
        self.out.log("Terminating dataset load for experiment {}".format(self.exp_id))

    def keep_running(self):
        # This is a separate method so that it can be replaced in tests
        return True


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--replay', is_flag=True, flag_value=True, help='Replay mode')
def load(app, verbose, replay, exp_config=None):
    """Import database state from an exported zip file and leave the server
    running until stopping the process with <control>-c.
    """
    if replay:
        exp_config = exp_config or {}
        exp_config['replay'] = True
    loader = LoadSessionRunner(app, Output(), verbose, exp_config)
    loader.run()


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
def logs(app):
    """Show the logs."""
    if app is None:
        raise TypeError("Select an experiment using the --app flag.")

    HerokuApp(dallinger_uid=app).open_logs()


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
def monitor(app):
    """Set up application monitoring."""
    heroku_app = HerokuApp(dallinger_uid=app)
    webbrowser.open(heroku_app.dashboard_url)
    webbrowser.open("https://requester.mturk.com/mturk/manageHITs")
    heroku_app.open_logs()
    check_call(["open", heroku_app.db_uri])
    while _keep_running():
        summary = get_summary(app)
        click.clear()
        click.echo(header)
        click.echo("\nExperiment {}\n".format(app))
        click.echo(summary)
        time.sleep(10)


def _keep_running():
    """Patchable version of True"""
    return True


def bot_factory(url):
    """Import the current Bot class, which must be done at runtime, then
    return an instance.
    """
    from dallinger_experiment import Bot
    return Bot(url)


@dallinger.command()
@click.option('--app', default=None, help='Experiment id')
@click.option('--debug', default=None,
              help='Local debug recruitment url')
def bot(app, debug):
    """Run the experiment bot."""
    if debug is None:
        verify_id(None, None, app)

    (id, tmp) = setup_experiment()

    if debug:
        url = debug
    else:
        heroku_app = HerokuApp(dallinger_uid=app)
        worker = generate_random_id()
        hit = generate_random_id()
        assignment = generate_random_id()
        ad_url = '{}/ad'.format(heroku_app.url)
        ad_parameters = 'assignmentId={}&hitId={}&workerId={}&mode=sandbox'
        ad_parameters = ad_parameters.format(assignment, hit, worker)
        url = '{}?{}'.format(ad_url, ad_parameters)
    bot = bot_factory(url)
    bot.run_experiment()


@dallinger.command()
def verify():
    """Verify that app is compatible with Dallinger."""
    verify_package(verbose=True)


@dallinger.command()
def rq_worker():
    """Start an rq worker in the context of dallinger."""
    setup_experiment()
    with Connection(conn):
        # right now we care about low queue for bots
        worker = Worker('low')
        worker.work()
