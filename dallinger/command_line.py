#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Dallinger command-line utility."""

import errno
import hashlib
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
import subprocess
import sys
import tempfile
import time
import uuid
import webbrowser

import click
from dallinger.config import get_config
import psycopg2
import redis
import requests

from dallinger import db
from dallinger import data
from dallinger import heroku
from dallinger.heroku import (
    app_name,
    scale_up_dynos
)
from dallinger.version import __version__

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


def print_header():
    """Print a fancy-looking header."""
    log("""
        ____        ____
       / __ \____ _/ / (_)___  ____ ____  _____
      / / / / __ `/ / / / __ \/ __ `/ _ \/ ___/
     / /_/ / /_/ / / / / / / / /_/ /  __/ /
    /_____/\__,_/_/_/_/_/ /_/\__, /\___/_/
                            /____/

                    Laboratory automation for
           the behavioral and social sciences.
    """, 0.5, False)


def log(msg, delay=0.5, chevrons=True, verbose=True):
    """Log a message to stdout."""
    if verbose:
        if chevrons:
            click.echo("\n❯❯ " + msg)
        else:
            click.echo(msg)
        time.sleep(delay)


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
    print_header()

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
        config.load_config()

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

    config.write_config(filter_sensitive=True)

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

    # Rename experiment.py to avoid psiTurk conflict.
    os.rename(
        os.path.join(dst, "experiment.py"),
        os.path.join(dst, "dallinger_experiment.py"))

    # Get dallinger package location.
    from pkg_resources import get_distribution
    dist = get_distribution('dallinger')
    src_base = os.path.join(dist.location, dist.project_name)

    heroku_files = [
        "Procfile",
        "psiturkapp.py",
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


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
def debug(verbose):
    """Run the experiment locally."""
    (id, tmp) = setup_experiment(debug=True, verbose=verbose)

    # Drop all the tables from the database.
    db.init_db(drop_all=True)

    # Switch to the temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Set the mode to debug.
    config = get_config()
    logfile = config.get('logfile')
    if logfile != '-':
        logfile = os.path.join(cwd, logfile)
    config.extend({
        "mode": u"debug",
        "launch_in_sandbox_mode": True,
        "logfile": logfile
    })
    config.write_config()

    # Start up the local server
    log("Starting up the server...")
    path = os.path.realpath(os.path.join(__file__, '..', 'heroku', 'psiturkapp.py'))
    p = subprocess.Popen(
        [sys.executable, '-u', path],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )

    # Wait for server to start
    ready = False
    for line in iter(p.stdout.readline, ''):
        if re.match('^Ready.$', line):
            ready = True
            break
        sys.stdout.write(line)

    if ready:
        host = config.get('host')
        port = config.get('port')
        public_interface = "{}:{}".format(host, port)
        log("Server is running on {}. Press Ctrl+C to exit.".format(public_interface))

        # Call endpoint to launch the experiment
        log("Launching the experiment...")
        time.sleep(4)
        subprocess.check_call(
            'curl --data "" http://{}/launch'.format(public_interface),
            shell=True)

        # Monitor output from server process
        for line in iter(p.stdout.readline, ''):
            sys.stdout.write(line)

            # Open browser for new participants
            match = re.search('New participant requested: (.*)$', line)
            if match:
                url = match.group(1)
                webbrowser.open(url, new=1, autoraise=True)

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

    # Log in to Heroku if we aren't already.
    log("Making sure that you are logged in to Heroku.")
    heroku.log_in()
    click.echo("")

    # Change to temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Commit Heroku-specific files to tmp folder's git repo.
    cmds = ["git init",
            "git add --all",
            'git commit -m "Experiment ' + id + '"']
    for cmd in cmds:
        subprocess.check_call(cmd, stdout=out, shell=True)
        time.sleep(0.5)

    # Load configuration.
    config = get_config()
    if not config.ready:
        config.load_config()

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
    database_size = config.get('database_size')

    try:
        if config.get('whimsical'):
            whimsical = "true"
        else:
            whimsical = "false"
    except:
        whimsical = "false"

    # Set up postgres database and AWS/psiTurk environment variables.
    cmds = [
        "heroku addons:create heroku-postgresql:{}".format(quote(database_size)),

        "heroku pg:wait",

        "heroku addons:create heroku-redis:premium-0",

        "heroku addons:create papertrail",

        "heroku config:set HOST=" +
        app_name(id) + ".herokuapp.com",

        "heroku config:set aws_access_key_id=" +
        quote(config.get('aws_access_key_id')),

        "heroku config:set aws_secret_access_key=" +
        quote(config.get('aws_secret_access_key')),

        "heroku config:set aws_region=" +
        quote(config.get('aws_region')),

        "heroku config:set psiturk_access_key_id=" +
        quote(config.get('psiturk_access_key_id')),

        "heroku config:set psiturk_secret_access_id=" +
        quote(config.get('psiturk_secret_access_id')),

        "heroku config:set auto_recruit={}".format(config.get('auto_recruit')),

        "heroku config:set dallinger_email_username=" +
        quote(config.get('dallinger_email_address')),

        "heroku config:set dallinger_email_key=" +
        quote(config.get('dallinger_email_password')),

        "heroku config:set heroku_email_address=" +
        quote(config.get('heroku_email_address')),

        "heroku config:set heroku_password=" +
        quote(config.get('heroku_password')),

        "heroku config:set whimsical={}".format(whimsical),
    ]
    for cmd in cmds:
        subprocess.check_call(
            cmd + " --app " + app_name(id), stdout=out, shell=True)

    # Wait for Redis database to be ready.
    log("Waiting for Redis...")
    ready = False
    while not ready:
        redis_URL = subprocess.check_output(
            "heroku config:get REDIS_URL --app {}".format(app_name(id)),
            shell=True
        )
        r = redis.from_url(redis_URL)
        try:
            r.set("foo", "bar")
            ready = True
        except redis.exceptions.ConnectionError:
            time.sleep(2)

    log("Saving the URL of the postgres database...")
    db_url = subprocess.check_output(
        "heroku config:get DATABASE_URL --app " + app_name(id), shell=True)
    # Set the notification URL and database URL in the config file.
    config.extend({
        "notification_url": u"http://" + app_name(id) + ".herokuapp.com/notifications",
        "database_url": db_url.rstrip().decode('utf8'),
    })
    config.write_config()

    subprocess.check_call("git add config.txt", stdout=out, shell=True),
    time.sleep(0.25)
    subprocess.check_call(
        'git commit -m "Save URLs for database and notifications"',
        stdout=out,
        shell=True)
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    subprocess.check_call(
        "git push heroku HEAD:master", stdout=out, stderr=out, shell=True)

    log("Scaling up the dynos...")
    scale_up_dynos(app_name(id))

    time.sleep(8)

    # Launch the experiment.
    log("Launching the experiment on MTurk...")
    subprocess.check_call(
        'curl --data "" http://{}.herokuapp.com/launch'.format(app_name(id)),
        shell=True)

    time.sleep(8)

    url = subprocess.check_output(
        "heroku logs --app " + app_name(id) + " | sort | " +
        "sed -n 's|.*URL:||p'", shell=True)

    log("URLs:")
    click.echo(url)

    # Return to the branch whence we came.
    os.chdir(cwd)

    log("Completed deployment of experiment " + id + ".")


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='ID of the sandboxed experiment')
def sandbox(verbose, app):
    """Deploy app using Heroku to the MTurk Sandbox."""
    # Load configuration.
    config = get_config()
    config.load_config()

    # Set the mode.
    config.extend({"mode": u"sandbox",
                   "logfile": u"-",
                   "launch_in_sandbox_mode": True})

    # Do shared setup.
    deploy_sandbox_shared_setup(verbose=verbose, app=app)


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='ID of the deployed experiment')
def deploy(verbose, app):
    """Deploy app using Heroku to MTurk."""
    # Load configuration.
    config = get_config()
    config.load_config()

    # Set the mode.
    config.extend({"mode": u"sandbox",
                   "logfile": u"-",
                   "launch_in_sandbox_mode": False})

    # Do shared setup.
    deploy_sandbox_shared_setup(verbose=verbose, app=app)


@dallinger.command()
@click.option('--qualification')
@click.option('--value')
@click.option('--worker')
def qualify(qualification, value, worker):
    """Assign a qualification to a worker."""
    # create connection to AWS
    from boto.mturk.connection import MTurkConnection
    config = get_config()
    config.load_config()
    aws_access_key_id = config.get('aws_access_key_id')
    aws_secret_access_key = config.get('aws_secret_access_key')
    conn = MTurkConnection(aws_access_key_id, aws_secret_access_key)

    def get_workers_with_qualification(qualification):
        """Get workers with the given qualification."""
        results = []
        continue_flag = True
        page = 1
        while(continue_flag):
            new_results = conn.get_qualifications_for_qualification_type(
                qualification,
                page_size=100,
                page_number=page)

            if(len(new_results) == 0):
                continue_flag = False
            else:
                results.extend(new_results)
                page = page + 1

        return results

    results = get_workers_with_qualification(qualification)
    workers = [x.SubjectId for x in results]

    # assign the qualification
    click.echo(
        "Assigning qualification {} with value {} to worker {}".format(
            qualification,
            value,
            worker))

    if worker in workers:
        result = conn.update_qualification_score(qualification, worker, value)
    else:
        result = conn.assign_qualification(qualification, worker, value)

    if result:
        click.echo(result)

    # print out the current set of workers with the qualification
    results = get_workers_with_qualification(qualification)

    click.echo("{} workers with qualification {}:".format(
        len(results),
        qualification))

    values = [r.IntegerValue for r in results]
    unique_values = list(set([r.IntegerValue for r in results]))
    for v in unique_values:
        click.echo("{} with value {}".format(
            len([val for val in values if val == v]),
            v))


def dump_database(id):
    """Backup the Postgres database locally."""
    log("Generating a backup of the database on Heroku...")

    dump_filename = "data.dump"
    data_directory = "data"
    dump_dir = os.path.join(data_directory, id)
    if not os.path.exists(dump_dir):
        os.makedirs(dump_dir)

    try:
        FNULL = open(os.devnull, 'w')
        subprocess.call([
            "heroku",
            "pg:backups",
            "capture"
            "--app",
            app_name(id)
        ], stdout=FNULL, stderr=FNULL)

        subprocess.call([  # for more recent versions of Heroku CLI.
            "heroku",
            "pg:backups:capture",
            "--app",
            app_name(id)
        ], stdout=FNULL, stderr=FNULL)

    except Exception:
        pass

    backup_url = subprocess.check_output([
        "heroku",
        "pg:backups",
        "public-url",
        "--app",
        app_name(id)
    ])

    backup_url = backup_url.replace('"', '').rstrip()
    backup_url = re.search("https:.*", backup_url).group(0)
    print(backup_url)

    log("Downloading the backup...")
    dump_path = os.path.join(dump_dir, dump_filename)
    with open(dump_path, 'wb') as file:
        subprocess.check_call([
            'curl',
            '-o',
            dump_path,
            backup_url
        ], stdout=file)

    return dump_path


def backup(app):
    """Dump the database."""
    dump_path = dump_database(app)

    config = get_config()
    config.load_config()

    conn = boto.connect_s3(
        config.get('aws_access_key_id'),
        config.get('aws_secret_access_key'),
    )

    s3_bucket_name = "dallinger-{}".format(
        hashlib.sha256(conn.get_canonical_user_id()).hexdigest()[0:8])

    if not conn.lookup(s3_bucket_name):
        bucket = conn.create_bucket(
            s3_bucket_name,
            location=boto.s3.connection.Location.DEFAULT
        )
    else:
        bucket = conn.get_bucket(s3_bucket_name)

    k = boto.s3.key.Key(bucket)
    k.key = '{}.dump'.format(app)
    k.set_contents_from_filename(dump_path)
    url = k.generate_url(expires_in=0, query_auth=False)

    log("The database backup URL is...")
    print(url)


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def hibernate(app):
    """Pause an experiment and remove costly resources."""
    backup(app)

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
@click.option('--app', default=None, help='ID of the deployed experiment')
def destroy(app):
    """Tear down an experiment server."""
    destroy_server(app)


def destroy_server(app):
    """Tear down an experiment server."""
    subprocess.check_call([
        "heroku",
        "destroy",
        "--app",
        app_name(app),
        "--confirm",
        app_name(app),
    ])


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
@click.option('--databaseurl', default=None, help='URL of the database')
def awaken(app, databaseurl):
    """Restore the database from a given url."""
    id = app
    config = get_config()
    config.load_config()

    database_size = config.get('database_size')

    subprocess.check_call(
        "heroku addons:create heroku-postgresql:{} --app {}".format(
            database_size,
            app_name(id)),
        shell=True)

    subprocess.check_call(
        "heroku pg:wait --app {}".format(app_name(id)),
        shell=True)

    conn = boto.connect_s3(
        config.get('aws_access_key_id'),
        config.get('aws_secret_access_key'),
    )

    s3_bucket_name = "dallinger-{}".format(
        hashlib.sha256(conn.get_canonical_user_id()).hexdigest()[0:8])

    bucket = conn.get_bucket(s3_bucket_name)
    key = bucket.lookup('{}.dump'.format(id))
    url = key.generate_url(expires_in=300)

    cmd = "heroku pg:backups restore"
    subprocess.check_call(
        "{} '{}' DATABASE_URL --app {} --confirm {}".format(
            cmd,
            url,
            app_name(id),
            app_name(id)),
        shell=True)

    subprocess.check_call(
        "heroku addons:create heroku-redis:premium-0 --app {}".format(app_name(id)),
        shell=True)

    # Scale up the dynos.
    log("Scaling up the dynos...")
    scale_up_dynos(app_name(id))


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
@click.option('--local', is_flag=True, flag_value=True,
              help='Export local data')
def export(app, local):
    """Export the data."""
    print_header()

    id = str(app)

    export_data(id, local)


def export_data(id, local=False):
    """Allow calling export from experiments"""

    log("Preparing to export the data...")

    subdata_path = os.path.join("data", id, "data")

    # Create the data package if it doesn't already exist.
    try:
        os.makedirs(subdata_path)

    except OSError as exc:
        if exc.errno == errno.EEXIST and os.path.isdir(subdata_path):
            pass
        else:
            raise

    # Copy the experiment code into a code/ subdirectory
    try:
        shutil.copyfile(
            os.path.join("snapshots", id + "-code.zip"),
            os.path.join("data", id, id + "-code.zip")
        )

    except:
        pass

    # Copy in the DATA readme.
    # open(os.path.join(id, "README.txt"), "a").close()

    # Save the experiment id.
    with open(os.path.join("data", id, "experiment_id.md"), "a+") as file:
        file.write(id)

    if not local:
        # Export the logs
        subprocess.check_call(
            "heroku logs " +
            "-n 10000 > " + os.path.join("data", id, "server_logs.md") +
            " --app " + app_name(id),
            shell=True)

    try:
        subprocess.call([
            "dropdb",
            app_name(id),
        ])
    except Exception:
        pass

    subprocess.call([
        "heroku",
        "pg:pull",
        "DATABASE_URL",
        app_name(id),
        "--app",
        app_name(id),
    ])

    for table in data.table_names:
        subprocess.check_call(
            "psql -d " + app_name(id) +
            " --command=\"\\copy " + table + " to \'" +
            os.path.join(subdata_path, table) + ".csv\' csv header\"",
            shell=True)

    log("Zipping up the package...")
    shutil.make_archive(
        os.path.join("data", id + "-data"),
        "zip",
        os.path.join("data", id)
    )

    shutil.rmtree(os.path.join("data", id))

    log("Done. Data available in {}.zip".format(id))

    cwd = os.getcwd()
    export_filename = os.path.join(cwd, "data", '{}-data.zip'.format(id))
    return export_filename


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def logs(app):
    """Show the logs."""
    if app is None:
        raise TypeError("Select an experiment using the --app flag.")
    else:
        subprocess.check_call(
            "heroku addons:open papertrail --app " + app_name(app),
            shell=True)


@dallinger.command()
def verify():
    """Verify that app is compatible with Dallinger."""
    verify_package(verbose=True)


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

    # Check front-end files do not exist
    files = [
        os.path.join("templates", "complete.html"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "launch.html"),
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
