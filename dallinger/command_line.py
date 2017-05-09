#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Dallinger command-line utility."""

import imp
import inspect
import os
import pkg_resources
import psutil
import re
try:
    from pipes import quote
except ImportError:
    # Python >= 3.3
    from shlex import quote
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
import webbrowser

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
from dallinger.heroku import (
    app_name,
    scale_up_dynos
)
from dallinger.heroku.worker import conn
from dallinger.mturk import MTurkService
from dallinger import registration
from dallinger.utils import generate_random_id
from dallinger.utils import get_base_url
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


def verify_id(ctx, param, app):
    """Verify the experiment id."""
    if app is None:
        raise TypeError("Select an experiment using the --app flag.")
    elif app[0:5] == "dlgr-":
        raise ValueError("The --app flag requires the full "
                         "UUID beginning with {}-...".format(app[5:13]))


def verify_package(verbose=True):
    """Ensure the package has a config file and a valid experiment file."""
    is_passing = True

    # Check for existence of required files.
    required_files = [
        "config.txt",
        "experiment.py",
        "requirements.txt",
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
        for f in ["experiment.py", "config.txt"]:
            shutil.copyfile(f, os.path.join(tmp, f))

        cwd = os.getcwd()
        os.chdir(tmp)

        open("__init__.py", "a").close()
        exp = imp.load_source('experiment', os.path.join(tmp, "experiment.py"))

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

    # Make sure there's a help file.
    is_txt_readme = os.path.exists("README.md")
    is_md_readme = os.path.exists("README.txt")
    if (not is_md_readme) and (not is_txt_readme):
        is_passing = False
        log("✗ README.txt or README.md is MISSING.",
            delay=0, chevrons=False, verbose=verbose)
    else:
        log("✓ README is OK",
            delay=0, chevrons=False, verbose=verbose)

    # Check base_payment is correct
    config = get_config()
    if not config.ready:
        config.load()
    base_pay = config.get('base_payment')
    dollarFormat = "{:.2f}".format(base_pay)
    if base_pay <= 0:
        log("✗ base_payment must be positive value in config.txt.",
            delay=0, chevrons=False, verbose=verbose)
        return False
    if str(base_pay) != str(dollarFormat):
        log("✗ base_payment must be in [dollars].[cents] format in config.txt. Try changing "
            "{0} to {1}.".format(base_pay, dollarFormat), delay=0, chevrons=False, verbose=verbose)
        return False

    # Check front-end files do not exist
    files = [
        os.path.join("templates", "complete.html"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "thanks.html"),
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "scripts", "dallinger.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "robots.txt")
    ]

    for f in files:
        if os.path.exists(f):
            log("✗ {} will CONFLICT with shared front-end files inserted at run-time, "
                "please delete or rename.".format(f),
                delay=0, chevrons=False, verbose=verbose)
            return False

    log("✓ no file conflicts", delay=0, chevrons=False, verbose=verbose)

    return is_passing


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, '--version', '-v', message='%(version)s')
def dallinger():
    """Set up Dallinger as a name space."""
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
        dallinger_module_path = os.path.dirname(os.path.realpath(__file__))
        src = os.path.join(dallinger_module_path, "config", config_name)
        shutil.copyfile(src, config_path)


def setup_experiment(debug=True, verbose=False, app=None, exp_config=None):
    """Check the app and, if compatible with Dallinger, freeze its state."""
    log(header, chevrons=False)

    # Verify that the package is usable.
    log("Verifying that directory is compatible with Dallinger...")
    if not verify_package(verbose=verbose):
        raise AssertionError(
            "This is not a valid Dallinger app. " +
            "Fix the errors and then try running 'dallinger verify'.")

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
    except:
        dependencies = []

    pkg_resources.require(dependencies)

    # Generate a unique id for this experiment.
    generated_uid = public_id = str(uuid.uuid4())

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
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "complete.html"),
        os.path.join("templates", "thanks.html"),
        os.path.join("templates", "waiting.html"),
        os.path.join("static", "robots.txt")
    ]

    for filename in frontend_files:
        src = os.path.join(src_base, "frontend", filename)
        shutil.copy(src, os.path.join(dst, filename))

    time.sleep(0.25)

    os.chdir(cwd)

    return (public_id, dst)


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def summary(app):
    """Print a summary of a deployed app's status."""
    verify_id(app)
    r = requests.get('https://{}.herokuapp.com/summary'.format(app_name(app)))
    summary = r.json()['summary']
    click.echo("\nstatus \t| count")
    click.echo("----------------")
    for s in summary:
        click.echo("{}\t| {}".format(s[0], s[1]))
    num_101s = sum([s[1] for s in summary if s[0] == 101])
    num_10xs = sum([s[1] for s in summary if s[0] >= 100])
    if num_10xs > 0:
        click.echo("\nYield: {:.2%}".format(1.0 * num_101s / num_10xs))


def _handle_launch_data(url):
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
def debug(verbose, bot, exp_config=None):
    """Run the experiment locally."""
    exp_config = exp_config or {}
    exp_config.update({
        "mode": u"debug",
        "loglevel": 0,
    })
    if bot:
        exp_config["recruiter"] = u"bots"

    (id, tmp) = setup_experiment(verbose=verbose, exp_config=exp_config)

    # Switch to the temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Set the mode to debug.
    config = get_config()
    logfile = config.get('logfile')
    if logfile and logfile != '-':
        logfile = os.path.join(cwd, logfile)
        config.extend({'logfile': logfile})
        config.write()

    # Drop all the tables from the database.
    db.init_db(drop_all=True)

    # Start up the local server
    log("Starting up the server...")
    port = config.get('port')
    try:
        p = subprocess.Popen(
            ['heroku', 'local', '-p', str(port),
             "web={},worker={}".format(config.get('num_dynos_web', 1),
                                       config.get('num_dynos_worker', 1))],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError:
        error("Couldn't start Heroku for local debugging.")
        raise

    try:
        # Wait for server to start
        ready = False
        for line in iter(p.stdout.readline, ''):
            if verbose:
                sys.stdout.write(line)
            line = line.strip()
            if re.match('^.*? worker.1 .*? Connection refused.$', line):
                error('Could not connect to redis instance, experiment may not behave correctly.')
            if not verbose and re.match('^.*? web.1 .*? \[ERROR\] (.*?)$', line):
                error(line)
            if not verbose and re.match('\[DONE\] Killing all processes', line):
                error(
                    'There was an error while starting the server. '
                    'Run with --verbose for details.'
                )
            if re.match('^.*? \d+ workers$', line):
                ready = True
                break

        if ready:
            base_url = get_base_url()
            log("Server is running on {}. Press Ctrl+C to exit.".format(base_url))

            # Call endpoint to launch the experiment
            log("Launching the experiment...")
            time.sleep(4)
            _handle_launch_data('{}/launch'.format(base_url))

            closed = False
            status_url = base_url + '/summary'
            exp_data = {}
            # Monitor output from server process
            for line in iter(p.stdout.readline, ''):
                if verbose:
                    sys.stdout.write(line)

                # start checking for completion status
                if closed:
                    time.sleep(10)
                    try:
                        resp = requests.get(status_url)
                        exp_data = resp.json()
                    except (ValueError, requests.exceptions.RequestException):
                        error('Error fetching experiment status.')
                    log('Experiment summary: {}'.format(exp_data))
                    if exp_data.get('completed', False):
                        log('Experiment completed, all nodes filled.')
                        break
                    continue

                # Open browser for new participants
                match = re.search('New participant requested: (.*)$', line)
                if match:
                    url = match.group(1)
                    webbrowser.open(url, new=1, autoraise=True)

                # Is recruitment over? We can end the loop, and check
                # experiment status
                match = re.search('Close recruitment.$', line)
                if match:
                    log('Recruitment is complete.')
                    closed = True

    finally:
        try:
            # It seems we need to explicitly kill all subprocesses with a SIGINT
            int_signal = getattr(signal, 'CTRL_C_EVENT', signal.SIGINT)
            for sub in psutil.Process(p.pid).children(recursive=True):
                os.kill(sub.pid, int_signal)
            p.terminate()
            log("Local Heroku process terminated")
        except OSError:
            log("Local Heroku process already terminated")
            log(traceback.format_exc())

    log("Completed debugging of experiment with id " + id)
    os.chdir(cwd)


def deploy_sandbox_shared_setup(verbose=True, app=None, web_procs=1, exp_config=None):
    """Set up Git, push to Heroku, and launch the app."""
    if verbose:
        out = None
    else:
        out = open(os.devnull, 'w')

    (id, tmp) = setup_experiment(debug=False, verbose=verbose, app=app,
                                 exp_config=exp_config)

    # Register the experiment using all configured registration services.
    config = get_config()
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
    subprocess.check_call(["git", "init"], stdout=out)
    subprocess.check_call(["git", "add", "--all"], stdout=out)
    subprocess.check_call(
        ["git", "commit", "-m", '"Experiment {}"'.format(id)],
        stdout=out,
    )

    # Load configuration.
    config = get_config()
    if not config.ready:
        config.load()

    # Initialize the app on Heroku.
    log("Initializing app on Heroku...")

    create_cmd = [
        "heroku",
        "apps:create",
        app_name(id),
        "--buildpack",
        "https://github.com/thenovices/heroku-buildpack-scipy",
    ]

    # If a team is specified, assign the app to the team.
    try:
        team = config.get("heroku_team", None)
        if team:
            create_cmd.extend(["--org", team])
    except Exception:
        pass

    subprocess.check_call(create_cmd, stdout=out)

    subprocess.check_call([
        "heroku",
        "buildpacks:add",
        "https://github.com/stomita/heroku-buildpack-phantomjs",
    ])

    database_size = config.get('database_size')

    # Set up postgres database and AWS environment variables.
    cmds = [
        ["heroku", "addons:create", "heroku-postgresql:{}".format(quote(database_size))],
        ["heroku", "addons:create", "heroku-redis:premium-0"],
        ["heroku", "addons:create", "papertrail"],
    ]
    for cmd in cmds:
        subprocess.check_call(cmd + ["--app", app_name(id)], stdout=out)

    heroku_config = {
        "HOST": "{}.herokuapp.com".format(app_name(id)),
        "aws_access_key_id": config["aws_access_key_id"],
        "aws_secret_access_key": config["aws_secret_access_key"],
        "aws_region": config["aws_region"],
        "auto_recruit": config["auto_recruit"],
        "dallinger_email_username": config["dallinger_email_address"],
        "dallinger_email_key": config["dallinger_email_password"],
        "whimsical": config["whimsical"],
    }

    for key in heroku_config:
        subprocess.check_call([
            "heroku",
            "config:set",
            "{}={}".format(key, quote(str(heroku_config[key]))),
            "--app", app_name(id)
        ], stdout=out)

    # Wait for Redis database to be ready.
    log("Waiting for Redis...")
    ready = False
    while not ready:
        redis_url = subprocess.check_output([
            "heroku", "config:get", "REDIS_URL", "--app", app_name(id),
        ])
        r = redis.from_url(redis_url)
        try:
            r.set("foo", "bar")
            ready = True
        except redis.exceptions.ConnectionError:
            time.sleep(2)

    log("Saving the URL of the postgres database...")
    subprocess.check_call(["heroku", "pg:wait", "--app", app_name(id)])
    db_url = subprocess.check_output([
        "heroku", "config:get", "DATABASE_URL", "--app", app_name(id)
    ])

    # Set the notification URL and database URL in the config file.
    config.extend({
        "notification_url": u"http://" + app_name(id) + ".herokuapp.com/notifications",
        "database_url": db_url.rstrip().decode('utf8'),
    })
    config.write()

    subprocess.check_call(["git", "add", "config.txt"], stdout=out),
    time.sleep(0.25)
    subprocess.check_call(
        ["git", "commit", "-m", '"Save URLs for database and notifications"'],
        stdout=out
    )
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    subprocess.check_call(
        ["git", "push", "heroku", "HEAD:master"],
        stdout=out,
        stderr=out
    )

    log("Scaling up the dynos...")
    scale_up_dynos(app_name(id))

    time.sleep(8)

    # Launch the experiment.
    log("Launching the experiment on MTurk...")

    launch_data = _handle_launch_data('https://{}.herokuapp.com/launch'.format(app_name(id)))
    log("URLs:")
    log("App home: https://{}.herokuapp.com/".format(app_name(id)), chevrons=False)
    log("Initial recruitment: {}".format(launch_data.get('recruitment_url', None)), chevrons=False)

    # Return to the branch whence we came.
    os.chdir(cwd)

    log("Completed deployment of experiment " + id + ".")


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
def sandbox(verbose, app):
    """Deploy app using Heroku to the MTurk Sandbox."""
    # Load configuration.
    config = get_config()
    config.load()

    # Set the mode.
    config.extend({
        "mode": u"sandbox",
        "logfile": u"-",
    })

    # Do shared setup.
    deploy_sandbox_shared_setup(verbose=verbose, app=app)


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='ID of the deployed experiment')
def deploy(verbose, app):
    """Deploy app using Heroku to MTurk."""
    # Load configuration.
    config = get_config()
    config.load()

    # Set the mode.
    config.extend({
        "mode": u"live",
        "logfile": u"-",
    })

    # Do shared setup.
    deploy_sandbox_shared_setup(verbose=verbose, app=app)


@dallinger.command()
@click.option('--qualification')
@click.option('--value')
@click.option('--worker')
def qualify(qualification, value, worker):
    """Assign a qualification to a worker."""
    config = get_config()
    config.load()
    mturk = MTurkService(
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key'),
        sandbox=(config.get('mode') == "sandbox"),
    )

    click.echo(
        "Assigning qualification {} with value {} to worker {}".format(
            qualification,
            value,
            worker)
    )

    if mturk.set_qualification_score(qualification, worker, value):
        click.echo('OK')

    # print out the current set of workers with the qualification
    results = list(mturk.get_workers_with_qualification(qualification))

    click.echo("{} workers with qualification {}:".format(
        len(results),
        qualification))

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

    for process in ["web", "worker", "clock"]:
        subprocess.check_call([
            "heroku",
            "ps:scale", "{}=0".format(process),
            "--app", app_name(app)
        ])

    log("Removing addons...")

    addons = [
        "heroku-postgresql",
        # "papertrail",
        "heroku-redis",
    ]
    for addon in addons:
        subprocess.check_call([
            "heroku",
            "addons:destroy", addon,
            "--app", app_name(app),
            "--confirm", app_name(app)
        ])


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.confirmation_option(prompt='Are you sure you want to destroy the app?')
def destroy(app):
    """Tear down an experiment server."""
    destroy_server(app)


def destroy_server(app):
    """Tear down an experiment server."""
    subprocess.check_call([
        "heroku",
        "destroy",
        "--app", app_name(app),
        "--confirm", app_name(app),
    ])


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.option('--databaseurl', default=None, help='URL of the database')
def awaken(app, databaseurl):
    """Restore the database from a given url."""
    id = app
    config = get_config()
    config.load()

    subprocess.check_call([
        "heroku",
        "addons:create",
        "heroku-postgresql:{}".format(config.get('database_size')),
        "--app", app_name(id),
    ])

    subprocess.check_call(["heroku", "pg:wait", "--app", app_name(id)])

    bucket = data.user_s3_bucket()
    key = bucket.lookup('{}.dump'.format(id))
    url = key.generate_url(expires_in=300)

    subprocess.check_call([
        "heroku", "pg:backups", "restore", "'{}'".format(url), "DATABASE_URL",
        "--app", app_name(id),
        "--confirm", app_name(id),
    ])

    subprocess.check_call([
        "heroku", "addons:create", "heroku-redis:premium-0",
        "--app", app_name(id)
    ])

    # Scale up the dynos.
    log("Scaling up the dynos...")
    scale_up_dynos(app_name(id))


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.option('--local', is_flag=True, flag_value=True,
              help='Export local data')
@click.option('--no-scrub', is_flag=True, flag_value=False,
              help='Scrub PII')
def export(app, local, no_scrub):
    """Export the data."""
    log(header, chevrons=False)
    data.export(str(app), local=local, scrub_pii=(not no_scrub))


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
def logs(app):
    """Show the logs."""
    subprocess.check_call([
        "heroku", "addons:open", "papertrail", "--app", app_name(app)
    ])


@dallinger.command()
@click.option('--app', default=None, help='Experiment id')
@click.option('--debug', default=None,
              help='Local debug recruitment url')
def bot(app, debug):
    """Run the experiment bot."""
    if debug is None:
        verify_id(app)

    (id, tmp) = setup_experiment()

    if debug:
        url = debug
    else:
        host = app_name(app)
        worker = generate_random_id()
        hit = generate_random_id()
        assignment = generate_random_id()
        ad_url = 'https://{}.herokuapp.com/ad'.format(host)
        ad_parameters = 'assignmentId={}&hitId={}&workerId={}&mode=sandbox'
        ad_parameters = ad_parameters.format(assignment, hit, worker)
        url = '{}?{}'.format(ad_url, ad_parameters)

    from dallinger_experiment import Bot
    bot = Bot(url)
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

