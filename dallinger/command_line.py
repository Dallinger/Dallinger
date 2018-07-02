#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Dallinger command-line utility."""

from __future__ import print_function
from __future__ import unicode_literals

from collections import Counter
from functools import wraps
from six.moves import shlex_quote as quote
import inspect
import os
import pkg_resources
import re
import shutil
import signal
import six
import sys
import tempfile
import threading
import time
import webbrowser

import click
import psycopg2
import redis
import requests
from rq import (
    Worker,
    Connection,
)

from dallinger.compat import is_command
from dallinger.config import get_config
from dallinger.config import initialize_experiment_package
from dallinger import data
from dallinger import db
from dallinger import heroku
from dallinger.heroku.messages import get_messenger
from dallinger.heroku.messages import HITSummary
from dallinger.heroku.worker import conn
from dallinger.heroku.tools import HerokuLocalWrapper
from dallinger.heroku.tools import HerokuApp
from dallinger.mturk import MTurkService
from dallinger.mturk import MTurkServiceException
from dallinger import recruiters
from dallinger import registration
from dallinger.utils import check_call
from dallinger.utils import ensure_directory
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
            click.echo("\n❯❯ " + msg)
        else:
            click.echo(msg)
        time.sleep(delay)


def error(msg, delay=0.5, chevrons=True, verbose=True):
    """Log a message to stdout."""
    if verbose:
        if chevrons:
            click.secho("\n❯❯ " + msg, err=True, fg='red')
        else:
            click.secho(msg, err=True, fg='red')
        time.sleep(delay)


def new_webbrowser_profile():
    if is_command('google-chrome'):
        new_chrome = webbrowser.Chrome()
        new_chrome.name = 'google-chrome'
        profile_directory = tempfile.mkdtemp()
        new_chrome.remote_args = webbrowser.Chrome.remote_args + [
            '--user-data-dir="{}"'.format(profile_directory)
        ]
        return new_chrome
    elif is_command('firefox'):
        new_firefox = webbrowser.Mozilla()
        new_firefox.name = 'firefox'
        profile_directory = tempfile.mkdtemp()
        new_firefox.remote_args = [
            '-profile', profile_directory, '-new-instance', '-no-remote', '-url', '%s',
        ]
        return new_firefox
    else:
        return webbrowser


def report_idle_after(seconds):
    """Report_idle_after after certain number of seconds."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            def _handle_timeout(signum, frame):
                config = get_config()
                if not config.ready:
                    config.load()
                summary = HITSummary(
                    assignment_id=None,
                    duration=seconds,
                    time_active=seconds,
                    app_id=config.get('id'),
                )
                with config.override({'whimsical': False}, strict=True):
                    messenger = get_messenger(summary, config)
                    log("Reporting problem with idle experiment...")
                    messenger.send_idle_experiment_msg()

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
        clone_dir = os.path.join(tmp, 'temp_exp_package')
        to_ignore = shutil.ignore_patterns(
            os.path.join(".git", "*"),
            "*.db",
            "snapshots",
            "data",
            "server.log"
        )
        shutil.copytree(os.getcwd(), clone_dir, ignore=to_ignore)

        initialize_experiment_package(clone_dir)
        from dallinger_experiment import experiment
        classes = inspect.getmembers(experiment, inspect.isclass)
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
        os.path.join("templates", "error-complete.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "thanks.html"),
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "scripts", "dallinger.js"),
        os.path.join("static", "scripts", "dallinger2.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "scripts", "tracker.js"),
        os.path.join("static", "robots.txt")
    ]

    for f in files:
        if os.path.exists(f):
            log("✗ {} OVERWRITES shared frontend files inserted at run-time".format(f),
                delay=0, chevrons=False, verbose=verbose)

    log("✓ no file conflicts", delay=0, chevrons=False, verbose=verbose)

    return is_passing


click.disable_unicode_literals_warning = True


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
    generated_uid = public_id = Experiment.make_uuid(app)

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
        "server.log",
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

    config.extend({'id': six.text_type(generated_uid)})

    config.write(filter_sensitive=True)

    # Zip up the temporary directory and place it in the cwd.
    if not debug:
        log("Freezing the experiment package...")
        shutil.make_archive(
            os.path.join(cwd, "snapshots", public_id + "-code"), "zip", dst)

    # Check directories.
    ensure_directory(os.path.join("static", "scripts"))
    ensure_directory(os.path.join("templates", "default"))
    ensure_directory(os.path.join("static", "css"))

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
        os.path.join("static", "scripts", "require.js"),
        os.path.join("static", "scripts", "reconnecting-websocket.js"),
        os.path.join("static", "scripts", "spin.min.js"),
        os.path.join("static", "scripts", "tracker.js"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "error-complete.html"),
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
    num_approved = sum([s[1] for s in summary if s[0] == "approved"])
    num_not_working = sum([s[1] for s in summary if s[0] != "working"])
    if num_not_working > 0:
        the_yield = 1.0 * num_approved / num_not_working
        out.append("\nYield: {:.2%}".format(the_yield))
    return "\n".join(out)


INITIAL_DELAY = 5
RETRIES = 4


def _handle_launch_data(url, error=error,
                        delay=INITIAL_DELAY, remaining=RETRIES):
    time.sleep(delay)
    remaining = remaining - 1
    launch_request = requests.post(url)
    try:
        launch_data = launch_request.json()
    except ValueError:
        error(
            "Error parsing response from /launch, check web dyno logs for details: "
            + launch_request.text
        )
        raise

    if not launch_request.ok:
        if remaining < 1:
            error('Experiment launch failed, check web dyno logs for details.')
            if launch_data.get('message'):
                error(launch_data['message'])
            launch_request.raise_for_status()
        delay = 2 * delay
        error('Experiment launch failed, retrying in {} seconds ...'.format(delay))
        return _handle_launch_data(url, error, delay, remaining)

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
    if config.get("mode") == "live":
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
    redis_size = config.get('redis_size', 'premium-0')
    addons = [
        "heroku-postgresql:{}".format(quote(database_size)),
        "heroku-redis:{}".format(quote(redis_size)),
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
        "smtp_username": config["smtp_username"],
        "smtp_password": config["smtp_password"],
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
        "notification_url": heroku_app.url + "/notifications",
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
        "logfile": "-",
    })

    # Do shared setup.
    deploy_sandbox_shared_setup(verbose=verbose, app=app)


def _mturk_service_from_config(sandbox):
    config = get_config()
    config.load()
    return MTurkService(
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key'),
        region_name=config.get('aws_region'),
        sandbox=sandbox,
    )


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='Experiment id')
@report_idle_after(21600)
def sandbox(verbose, app):
    """Deploy app using Heroku to the MTurk Sandbox."""
    _deploy_in_mode('sandbox', app, verbose)


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='ID of the deployed experiment')
@report_idle_after(21600)
def deploy(verbose, app):
    """Deploy app using Heroku to MTurk."""
    _deploy_in_mode('live', app, verbose)


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
    mturk = _mturk_service_from_config(sandbox)
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
        if mturk.set_qualification_score(qid, worker, int(value), notify=notify):
            click.echo('{} OK'.format(worker))

    # print out the current set of workers with the qualification
    results = list(mturk.get_workers_with_qualification(qid))

    click.echo("{} workers with qualification {}:".format(
        len(results),
        qid))

    for score, count in Counter([r['score'] for r in results]).items():
        click.echo("{} with value {}".format(count, score))


@dallinger.command()
@click.option('--qualification')
@click.option('--by_name', is_flag=True, flag_value=True,
              help='Use a qualification name, not an ID')
@click.option('--reason',
              default='Revoking automatically assigned Dallinger qualification',
              help='Reason for revoking qualification')
@click.option('--sandbox', is_flag=True, flag_value=True, help='Use the MTurk sandbox')
@click.argument('workers', nargs=-1)
def revoke(workers, qualification, by_name, reason, sandbox):
    """Revoke a qualification from 1 or more workers"""
    if not (workers and qualification):
        raise click.BadParameter(
            'Must specify a qualification ID or name, and at least one worker ID'
        )

    mturk = _mturk_service_from_config(sandbox)
    if by_name:
        result = mturk.get_qualification_type_by_name(qualification)
        if result is None:
            raise click.BadParameter(
                'No qualification with name "{}" exists.'.format(qualification))

        qid = result['id']
    else:
        qid = qualification

    if not click.confirm(
        '\n\nYou are about to revoke qualification "{}" '
        'for these workers:\n\t{}\n\n'
        'This will send an email to each of them from Amazon MTurk. '
        'Continue?'.format(qid, '\n\t'.join(workers))
    ):
        click.echo('Aborting...')
        return

    for worker in workers:
        if mturk.revoke_qualification(qid, worker, reason):
            click.echo(
                'Revoked qualification "{}" from worker "{}"'.format(qid, worker)
            )

    # print out the current set of workers with the qualification
    results = list(mturk.get_workers_with_qualification(qid))
    click.echo(
        'There are now {} workers with qualification "{}"'.format(len(results), qid)
    )


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
def hibernate(app):
    """Pause an experiment and remove costly resources."""
    log("The database backup URL is...")
    backup_url = data.backup(app)
    log(backup_url)

    log("Scaling down the web servers...")
    heroku_app = HerokuApp(app)
    heroku_app.scale_down_dynos()

    log("Removing addons...")

    addons = [
        "heroku-postgresql",
        # "papertrail",
        "heroku-redis",
    ]
    for addon in addons:
        heroku_app.addon_destroy(addon)


def _current_hits(service, app):
    return service.get_hits(
        hit_filter=lambda h: h.get('annotation') == app
    )


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.option('--sandbox', is_flag=True, flag_value=True,
              help='Is the app running in the sandbox?')
def hits(app, sandbox):
    """List hits for an experiment id."""
    hit_list = list(_current_hits(_mturk_service_from_config(sandbox), app))
    out = Output()
    out.log('Found {} hits for this experiment id: {}'.format(
        len(hit_list), ', '.join(h['id'] for h in hit_list)
    ))


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.option('--sandbox', is_flag=True, flag_value=True,
              help='Is the app running in the sandbox?')
def expire(app, sandbox):
    """Expire hits for an experiment id."""
    success = []
    failures = []
    service = _mturk_service_from_config(sandbox)
    hits = _current_hits(service, app)
    for hit in hits:
        hit_id = hit['id']
        try:
            service.expire_hit(hit_id)
            success.append(hit_id)
        except MTurkServiceException:
            failures.append(hit_id)
    out = Output()
    if success:
        out.log('Expired {} hits: {}'.format(len(success), ', '.join(success)))
    if failures:
        out.log('Could not expire {} hits: {}'.format(
            len(failures), ', '.join(failures)
        ))
    if not success and not failures:
        out.log('No hits found for this application.')
        if not sandbox:
            out.log(
                'If this experiment was run in the MTurk sandbox, use: '
                '`dallinger expire --sandbox --app {}`'.format(app)
            )
    if not success:
        sys.exit(1)


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.confirmation_option(prompt='Are you sure you want to destroy the app?')
@click.option(
    '--expire-hit', is_flag=True, flag_value=True,
    prompt='Would you like to expire all hits associated with this experiment id?',
    help='Expire any hits associated with this experiment.')
@click.option('--sandbox', is_flag=True, flag_value=True,
              help='Is the app running in the sandbox?')
@click.pass_context
def destroy(ctx, app, expire_hit, sandbox):
    """Tear down an experiment server."""
    HerokuApp(app).destroy()
    if expire_hit:
        ctx.invoke(expire, app=app, sandbox=sandbox)


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

    heroku_app.addon("heroku-redis:{}".format(config.get(
        'redis_size', 'premium-0'
    )))
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
        self.blather = blather


class LocalSessionRunner(object):

    exp_id = None
    tmp_dir = None
    dispatch = {}  # Subclass may provide handlers for Heroku process output

    def configure(self):
        self.exp_config.update({
            "mode": "debug",
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
        self.complete = False
        self.status_thread = None

    def configure(self):
        super(DebugSessionRunner, self).configure()
        if self.bot:
            self.exp_config["recruiter"] = "bots"

    def execute(self, heroku):
        base_url = get_base_url()
        self.out.log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))
        self.out.log("Launching the experiment...")
        try:
            result = _handle_launch_data('{}/launch'.format(base_url), error=self.out.error)
        except Exception:
            # Show output from server
            self.dispatch[r'POST /launch'] = 'launch_request_complete'
            heroku.monitor(listener=self.notify)
        else:
            if result['status'] == 'success':
                self.out.log(result['recruitment_msg'])
                self.heroku = heroku
                heroku.monitor(listener=self.notify)

    def launch_request_complete(self, match):
        return HerokuLocalWrapper.MONITOR_STOP

    def cleanup(self):
        log("Completed debugging of experiment with id " + self.exp_id)
        self.complete = True

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
        new_webbrowser_profile().open(url, new=1, autoraise=True)

    def recruitment_closed(self, match):
        """Recruitment is closed.

        Start a thread to check the experiment summary.
        """
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
        status_url = base_url + '/summary'
        while not self.complete:
            time.sleep(10)
            try:
                resp = requests.get(status_url)
                exp_data = resp.json()
            except (ValueError, requests.exceptions.RequestException):
                self.out.error('Error fetching experiment status.')
            else:
                self.out.log('Experiment summary: {}'.format(exp_data))
                if exp_data.get('completed', False):
                    self.out.log('Experiment completed, all nodes filled.')
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
        return super(DebugSessionRunner, self).notify(message)


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
            "mode": "debug",
            "loglevel": 0,
        })

        self.zip_path = data.find_experiment_export(self.app_id)
        if self.zip_path is None:
            msg = 'Dataset export for app id "{}" could not be found.'
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
        new_webbrowser_profile().open(url, new=1, autoraise=True)

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
    from dallinger_experiment.experiment import Bot
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
