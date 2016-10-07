#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Dallinger command-line utility."""

import imp
import inspect
import os
import pexpect
import pkg_resources
import re
import shutil
import subprocess
import tempfile
import time
import uuid

import boto
import click
from psiturk.psiturk_config import PsiturkConfig
import psycopg2
import requests

from dallinger import db
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


def ensure_heroku_logged_in():
    """Ensure that the user is logged in to Heroku."""
    p = pexpect.spawn("heroku auth:whoami")
    p.interact()
    click.echo("")


def heroku_id(id):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + id[0:8]


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, '--version', '-v', message='%(version)s')
def dallinger():
    """Set up Dallinger as a name space."""
    pass


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


def setup_experiment(debug=True, verbose=False, app=None):
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
    except psycopg2.OperationalError, e:
        if "could not connect to server" in str(e):
            raise RuntimeError("The Postgres server isn't running.")

    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    # Check that the demo-specific requirements are satisfied.
    try:
        with open("requirements.txt", "r") as f:
            dependencies = f.readlines()
    except:
        dependencies = []

    pkg_resources.require(dependencies)

    # Generate a unique id for this experiment.
    id = str(uuid.uuid4())

    # If the user provided an app name, use it everywhere that's user-facing.
    if app:
        id_long = id
        id = str(app)

    log("Experiment id is " + id + "")

    # Copy this directory into a temporary folder, ignoring .git
    dst = os.path.join(tempfile.mkdtemp(), id)
    to_ignore = shutil.ignore_patterns(
        ".git/*",
        "*.db",
        "snapshots",
        "data",
        "server.log"
    )
    shutil.copytree(os.getcwd(), dst, ignore=to_ignore)

    click.echo(dst)

    # Save the experiment id
    with open(os.path.join(dst, "experiment_id.txt"), "w") as file:
        if app:
            file.write(id_long)
        else:
            file.write(id)

    # Zip up the temporary directory and place it in the cwd.
    if not debug:
        log("Freezing the experiment package...")
        shutil.make_archive(
            os.path.join("snapshots", id + "-code"), "zip", dst)

    # Change directory to the temporary folder.
    cwd = os.getcwd()
    os.chdir(dst)

    # Check directories.
    if not os.path.exists("static/scripts"):
        os.makedirs("static/scripts")
    if not os.path.exists("templates"):
        os.makedirs("templates")
    if not os.path.exists("static/css"):
        os.makedirs("static/css")

    # Rename experiment.py to avoid psiTurk conflict.
    os.rename(
        os.path.join(dst, "experiment.py"),
        os.path.join(dst, "dallinger_experiment.py"))

    # Copy files into this experiment package.
    src = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "custom.py")
    shutil.copy(src, os.path.join(dst, "custom.py"))

    heroku_files = [
        "Procfile",
        "psiturkapp.py",
        "worker.py",
        "clock.py",
    ]

    for filename in heroku_files:
        src = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "heroku",
            filename)
        shutil.copy(src, os.path.join(dst, filename))

    clock_on = config.getboolean('Server Parameters', 'clock_on')

    # If the clock process has been disabled, overwrite the Procfile.
    if not clock_on:
        src = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "heroku",
            "Procfile_no_clock")
        shutil.copy(src, os.path.join(dst, "Procfile"))

    frontend_files = [
        "static/css/dallinger.css",
        "static/scripts/dallinger.js",
        "static/scripts/reqwest.min.js",
        "templates/error_dallinger.html",
        "templates/launch.html",
        "templates/complete.html",
        "static/robots.txt"
    ]

    for filename in frontend_files:
        src = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "frontend",
            filename)
        shutil.copy(src, os.path.join(dst, filename))

    time.sleep(0.25)

    os.chdir(cwd)

    return (id, dst)


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def summary(app):
    """Print a summary of a deployed app's status."""
    r = requests.get('https://{}.herokuapp.com/summary'.format(heroku_id(app)))
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

    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    # Set the mode to debug.
    config.set("Experiment Configuration", "mode", "debug")
    config.set("Shell Parameters", "launch_in_sandbox_mode", "true")
    config.set(
        "Server Parameters",
        "logfile",
        os.path.join(cwd, config.get("Server Parameters", "logfile")))

    # Swap in the HotAirRecruiter
    os.rename("dallinger_experiment.py", "dallinger_experiment_tmp.py")
    with open("dallinger_experiment_tmp.py", "r+") as f:
        with open("dallinger_experiment.py", "w+") as f2:
            f2.write("from dallinger.recruiters import HotAirRecruiter\n")
            for idx, line in enumerate(f):
                if re.search("\s*self.recruiter = (.*)", line):
                    p = line.partition("self.recruiter =")
                    f2.write(p[0] + p[1] + ' HotAirRecruiter\n')
                else:
                    f2.write(line)

    os.remove("dallinger_experiment_tmp.py")

    # Set environment variables.
    vars = [
        ("AWS Access", "aws_access_key_id"),
        ("AWS Access", "aws_secret_access_key"),
        ("AWS Access", "aws_region"),
        ("psiTurk Access", "psiturk_access_key_id"),
        ("psiTurk Access", "psiturk_secret_access_id"),
    ]
    for var in vars:
        if var[0] not in os.environ:
            os.environ[var[1]] = config.get(var[0], var[1])

    if "HOST" not in os.environ:
        os.environ["HOST"] = config.get('Server Parameters', 'host')

    # Start up the local server
    log("Starting up the server...")

    # Try opening the psiTurk shell.
    try:
        p = pexpect.spawn("psiturk")
        p.expect_exact("]$")
        p.sendline("server on")
        p.expect_exact("Experiment server launching...")

        # Launche the experiment.
        time.sleep(4)

        host = config.get("Server Parameters", "host")
        port = config.get("Server Parameters", "port")

        subprocess.call(
            'curl --data "" http://{}:{}/launch'.format(host, port),
            shell=True)

        log("Here's the psiTurk shell...")
        p.interact()

    except Exception:
        click.echo("\nCouldn't open psiTurk shell. Internet connection okay?")

    log("Completed debugging of experiment with id " + id)
    os.chdir(cwd)


def scale_up_dynos(id):
    """Scale up the Heroku dynos."""
    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    dyno_type = config.get('Server Parameters', 'dyno_type')
    num_dynos_web = config.get('Server Parameters', 'num_dynos_web')
    num_dynos_worker = config.get('Server Parameters', 'num_dynos_worker')

    log("Scaling up the dynos...")
    subprocess.call(
        "heroku ps:scale web=" + str(num_dynos_web) + ":" +
        str(dyno_type) + " --app " + heroku_id(id), shell=True)

    subprocess.call(
        "heroku ps:scale worker=" + str(num_dynos_worker) + ":" +
        str(dyno_type) + " --app " + heroku_id(id), shell=True)

    clock_on = config.getboolean('Server Parameters', 'clock_on')
    if clock_on:
        subprocess.call(
            "heroku ps:scale clock=1:" + dyno_type + " --app " + heroku_id(id),
            shell=True)


def deploy_sandbox_shared_setup(verbose=True, app=None, web_procs=1):
    """Set up Git, push to Heroku, and launch the app."""
    if verbose:
        out = None
    else:
        out = open(os.devnull, 'w')

    (id, tmp) = setup_experiment(debug=False, verbose=verbose, app=app)

    # Log in to Heroku if we aren't already.
    log("Making sure that you are logged in to Heroku.")
    ensure_heroku_logged_in()

    # Change to temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Commit Heroku-specific files to tmp folder's git repo.
    cmds = ["git init",
            "git add --all",
            'git commit -m "Experiment ' + id + '"']
    for cmd in cmds:
        subprocess.call(cmd, stdout=out, shell=True)
        time.sleep(0.5)

    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    # Initialize the app on Heroku.
    log("Initializing app on Heroku...")
    subprocess.call(
        "heroku apps:create " + heroku_id(id) +
        " --buildpack https://github.com/thenovices/heroku-buildpack-scipy",
        stdout=out,
        shell=True)

    database_size = config.get('Database Parameters', 'database_size')

    try:
        if config.getboolean('Easter eggs', 'whimsical'):
            whimsical = "true"
        else:
            whimsical = "false"
    except:
        whimsical = "false"

    # Set up postgres database and AWS/psiTurk environment variables.
    cmds = [
        "heroku addons:create heroku-postgresql:{}".format(database_size),

        "heroku pg:wait",

        "heroku addons:create rediscloud:250",

        "heroku addons:create papertrail",

        "heroku config:set HOST=" +
        heroku_id(id) + ".herokuapp.com",

        "heroku config:set aws_access_key_id=" +
        config.get('AWS Access', 'aws_access_key_id'),

        "heroku config:set aws_secret_access_key=" +
        config.get('AWS Access', 'aws_secret_access_key'),

        "heroku config:set aws_region=" +
        config.get('AWS Access', 'aws_region'),

        "heroku config:set psiturk_access_key_id=" +
        config.get('psiTurk Access', 'psiturk_access_key_id'),

        "heroku config:set psiturk_secret_access_id=" +
        config.get('psiTurk Access', 'psiturk_secret_access_id'),

        "heroku config:set auto_recruit=" +
        config.get('Experiment Configuration', 'auto_recruit'),

        "heroku config:set dallinger_email_username=" +
        config.get('Email Access', 'dallinger_email_address'),

        "heroku config:set dallinger_email_key=" +
        config.get('Email Access', 'dallinger_email_password'),

        "heroku config:set heroku_email_address=" +
        config.get('Heroku Access', 'heroku_email_address'),

        "heroku config:set heroku_password=" +
        config.get('Heroku Access', 'heroku_password'),

        "heroku config:set whimsical=" + whimsical,
    ]
    for cmd in cmds:
        subprocess.call(
            cmd + " --app " + heroku_id(id), stdout=out, shell=True)

    # Set the notification URL in the cofig file to the notifications URL.
    config.set(
        "Server Parameters",
        "notification_url",
        "http://" + heroku_id(id) + ".herokuapp.com/notifications")

    # Set the database URL in the config file to the newly generated one.
    log("Saving the URL of the postgres database...")
    db_url = subprocess.check_output(
        "heroku config:get DATABASE_URL --app " + heroku_id(id), shell=True)
    config.set("Database Parameters", "database_url", db_url.rstrip())
    subprocess.call("git add config.txt", stdout=out, shell=True),
    time.sleep(0.25)
    subprocess.call(
        'git commit -m "Save URLs for database and notifications"',
        stdout=out,
        shell=True)
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    subprocess.call("git push heroku HEAD:master", stdout=out,
                    stderr=out, shell=True)

    scale_up_dynos(id)

    time.sleep(8)

    # Launch the experiment.
    log("Launching the experiment on MTurk...")
    subprocess.call(
        'curl --data "" http://{}.herokuapp.com/launch'.format(heroku_id(id)),
        shell=True)

    time.sleep(8)

    url = subprocess.check_output(
        "heroku logs --app " + heroku_id(id) + " | sort | " +
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
    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    # Set the mode.
    config.set("Experiment Configuration", "mode", "sandbox")
    config.set("Server Parameters", "logfile", "-")

    # Ensure that psiTurk is in sandbox mode.
    config.set("Shell Parameters", "launch_in_sandbox_mode", "true")

    # Do shared setup.
    deploy_sandbox_shared_setup(verbose=verbose, app=app)


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='ID of the deployed experiment')
def deploy(verbose, app):
    """Deploy app using Heroku to MTurk."""
    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    # Set the mode.
    config.set("Experiment Configuration", "mode", "deploy")
    config.set("Server Parameters", "logfile", "-")

    # Ensure that psiTurk is not in sandbox mode.
    config.set("Shell Parameters", "launch_in_sandbox_mode", "false")

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
    config = PsiturkConfig()
    config.load_config()
    aws_access_key_id = config.get('AWS Access', 'aws_access_key_id')
    aws_secret_access_key = config.get('AWS Access', 'aws_secret_access_key')
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

    subprocess.call(
        "heroku pg:backups capture --app " + heroku_id(id), shell=True)

    backup_url = subprocess.check_output(
        "heroku pg:backups public-url --app " + heroku_id(id), shell=True)
    backup_url = backup_url.replace('"', '').rstrip()
    backup_url = re.search("https:.*", backup_url).group(0)
    print(backup_url)

    log("Downloading the backup...")
    dump_path = os.path.join(dump_dir, dump_filename)
    with open(dump_path, 'wb') as file:
        subprocess.call(['curl', '-o', dump_path, backup_url], stdout=file)

    return dump_path


def backup(app):
    """Dump the database."""
    dump_path = dump_database(app)

    config = PsiturkConfig()
    config.load_config()

    conn = boto.connect_s3(
        config.get('AWS Access', 'aws_access_key_id'),
        config.get('AWS Access', 'aws_secret_access_key'),
    )

    bucket = conn.create_bucket(
        app,
        location=boto.s3.connection.Location.DEFAULT
    )

    k = boto.s3.key.Key(bucket)
    k.key = 'database.dump'
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
    subprocess.call("heroku ps:scale web=0" + " --app " + heroku_id(app), shell=True)
    subprocess.call("heroku ps:scale worker=0" + " --app " + heroku_id(app), shell=True)
    subprocess.call("heroku ps:scale clock=0" + " --app " + heroku_id(app), shell=True)

    log("Removing addons...")
    addons = [
        "heroku-postgresql",
        # "papertrail",
        "rediscloud",
    ]
    for addon in addons:
        subprocess.call(
            "heroku addons:destroy {} --app {} --confirm {}".format(
                addon,
                heroku_id(app),
                heroku_id(app)
            ),
            shell=True,
        )


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def destroy(app):
    """Tear down an experiment server."""
    subprocess.call(
        "heroku destroy --app {} --confirm {}".format(
            heroku_id(app),
            heroku_id(app)
        ),
        shell=True,
    )


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
@click.option('--databaseurl', default=None, help='URL of the database')
def awaken(app, databaseurl):
    """Restore the database from a given url."""
    config = PsiturkConfig()
    config.load_config()

    database_size = config.get('Database Parameters', 'database_size')

    subprocess.call(
        "heroku addons:create heroku-postgresql:{} --app {}".format(
            database_size,
            heroku_id(app)),
        shell=True)

    subprocess.call(
        "heroku pg:wait --app {}".format(heroku_id(app)),
        shell=True)

    conn = boto.connect_s3(
        config.get('AWS Access', 'aws_access_key_id'),
        config.get('AWS Access', 'aws_secret_access_key'),
    )

    bucket = conn.get_bucket(app)
    key = bucket.lookup('database.dump')
    url = key.generate_url(expires_in=300)

    cmd = "heroku pg:backups restore"
    subprocess.call(
        "{} '{}' DATABASE_URL --app {} --confirm {}".format(
            cmd,
            url,
            heroku_id(app),
            heroku_id(app)),
        shell=True)

    subprocess.call(
        "heroku addons:create rediscloud:250 --app {}".format(heroku_id(app)),
        shell=True)

    # Scale up the dynos.
    scale_up_dynos(app)


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
@click.option('--local', is_flag=True, flag_value=True,
              help='Export local data')
def export(app, local):
    """Export the data."""
    print_header()

    log("Preparing to export the data...")

    id = str(app)

    subdata_path = os.path.join("data", id, "data")

    # Create the data package
    os.makedirs(subdata_path)

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
        subprocess.call(
            "heroku logs " +
            "-n 10000 > " + os.path.join("data", id, "server_logs.md") +
            " --app " + heroku_id(id),
            shell=True)

        dump_path = dump_database(id)

        subprocess.call(
            "pg_restore --verbose --clean -d dallinger " +
            os.path.join("data", id) + "/data.dump",
            shell=True)

    all_tables = [
        "node",
        "network",
        "vector",
        "info",
        "transformation",
        "transmission",
        "participant",
        "notification",
        "question"
    ]

    for table in all_tables:
        subprocess.call(
            "psql -d dallinger --command=\"\\copy " + table + " to \'" +
            os.path.join(subdata_path, table) + ".csv\' csv header\"",
            shell=True)

    if not local:
        os.remove(dump_path)

    log("Zipping up the package...")
    shutil.make_archive(
        os.path.join("data", id + "-data"),
        "zip",
        os.path.join("data", id)
    )

    shutil.rmtree(os.path.join("data", id))

    log("Done. Data available in " + str(id) + ".zip")


@dallinger.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def logs(app):
    """Show the logs."""
    if app is None:
        raise TypeError("Select an experiment using the --app flag.")
    else:
        subprocess.call(
            "heroku addons:open papertrail --app " + heroku_id(app),
            shell=True)


@dallinger.command()
def verify():
    """Verify that app is compatible with Dallinger."""
    verify_package(verbose=True)


def verify_package(verbose=True):
    """Ensure the package has a config file and a valid experiment file."""
    is_passing = True

    # Check the config file.
    if os.path.exists("config.txt"):
        log("✓ config.txt is OK",
            delay=0, chevrons=False, verbose=verbose)
    else:
        log("✗ config.txt is MISSING",
            delay=0, chevrons=False, verbose=verbose)
        return False

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
            log("✓ experiment.py is OK",
                delay=0, chevrons=False, verbose=verbose)
        else:
            log("✗ experiment.py defines more than one experiment class.",
                delay=0, chevrons=False, verbose=verbose)
        os.chdir(cwd)

    else:
        log("✗ experiment.py is MISSING",
            delay=0, chevrons=False, verbose=verbose)
        is_passing = False

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
    if os.path.exists("templates/complete.html"):
        log("✗ templates/complete.html will CONFLICT with shared front-end files inserted at run-time, please delete or rename.",
            delay=0, chevrons=False, verbose=verbose)
        return False
    elif os.path.exists("templates/error_dallinger.html"):
        log("✗ templates/error_dallinger.html will CONFLICT with shared front-end files inserted at run-time, please delete or rename.",
            delay=0, chevrons=False, verbose=verbose)
        return False
    elif os.path.exists("templates/launch.html"):
        log("✗ templates/launch.html will CONFLICT with shared front-end files inserted at run-time, please delete or rename.",
            delay=0, chevrons=False, verbose=verbose)
        return False
    elif os.path.exists("static/css/dallinger.css"):
        log("✗ static/css/dallinger.css will CONFLICT with shared front-end files inserted at run-time, please delete or rename.",
            delay=0, chevrons=False, verbose=verbose)
        return False
    elif os.path.exists("static/scripts/dallinger.js"):
        log("✗ static/scripts/dallinger.js will CONFLICT with shared front-end files inserted at run-time, please delete or rename.",
            delay=0, chevrons=False, verbose=verbose)
        return False
    elif os.path.exists("static/scripts/reqwest.min.js"):
        log("✗ static/scripts/reqwest.min.js will CONFLICT with shared front-end files inserted at run-time, please delete or rename.",
            delay=0, chevrons=False, verbose=verbose)
        return False
    elif os.path.exists("static/robots.txt"):
        log("✗ static/robots.txt will CONFLICT with shared front-end files inserted at run-time, please delete or rename.",
            delay=0, chevrons=False, verbose=verbose)
        return False
    else:
        log("✓ no file conflicts",
            delay=0, chevrons=False, verbose=verbose)

    return is_passing
