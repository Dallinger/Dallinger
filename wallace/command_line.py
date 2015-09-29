#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Wallace command-line utility."""

import click
import time
import uuid
from psiturk.psiturk_config import PsiturkConfig
import os
import subprocess
import shutil
import pexpect
import tempfile
import inspect
import imp
import pkg_resources
import re
import psycopg2
from wallace import db
import requests

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


def print_header():
    """Print a fancy-looking header."""
    log("""
     _    _    __    __    __      __    ___  ____
    ( \/\/ )  /__\  (  )  (  )    /__\  / __)( ___)
     )    (  /(__)\  )(__  )(__  /(__)\ |(__  )__)
    (__/\__)(__)(__)(____)(____)(__)(__)\___)(____)

             a platform for experimental evolution.

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
    print ""


@click.group(context_settings=CONTEXT_SETTINGS)
def wallace():
    """Set up Wallace as a name space."""
    pass


def setup(debug=True, verbose=False):
    """Check the app and, if it's compatible with Wallace, freeze its state."""
    print_header()

    # Verify that the package is usable.
    log("Verifying that directory is compatible with Wallace...")
    if not verify_package(verbose=verbose):
        raise AssertionError(
            "This is not a valid Wallace app. " +
            "Fix the errors and then try running 'wallace verify'.")

    # Verify that the Postgres server is running.
    try:
        psycopg2.connect(database="x", user="postgres", password="nada")
    except psycopg2.OperationalError, e:
        if "could not connect to server" in str(e):
            raise RuntimeError("The Postgres server isn't running.")

    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    # Check that the version of Wallace specified in the config file is the one
    # that we are currently running.
    wallace_version = config.get('Experiment Configuration', 'wallace_version')
    this_version = pkg_resources.require("wallace")[0].version
    if wallace_version != this_version:
        raise AssertionError(
            "You are using Wallace v" + this_version + ", "
            "but the experiment requires v" + wallace_version)

    # Generate a unique id for this experiment.
    id = "w" + str(uuid.uuid4())[0:28]
    log("Running as experiment " + id + "...")

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

    print dst

    # Save the experiment id
    with open(os.path.join(dst, "experiment_id.txt"), "w") as file:
        file.write(id)

    # Zip up the temporary directory and place it in the cwd.
    if not debug:
        log("Freezing the experiment package...")
        shutil.make_archive(
            os.path.join("snapshots", id + "-code"), "zip", dst)

    # Change directory to the temporary folder.
    cwd = os.getcwd()
    os.chdir(dst)

    # Rename experiment.py to wallace_experiment.py to aviod psiTurk conflict.
    os.rename(
        os.path.join(dst, "experiment.py"),
        os.path.join(dst, "wallace_experiment.py"))

    # Copy files into this experiment package.
    src = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "custom.py")
    shutil.copy(src, os.path.join(dst, "custom.py"))

    heroku_files = [
        "Procfile",
        "requirements.txt",
        "psiturkapp.py",
        "worker.py"
    ]
    for filename in heroku_files:
        src = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "heroku",
            filename)
        shutil.copy(src, os.path.join(dst, filename))

    time.sleep(0.25)

    os.chdir(cwd)

    return (id, dst)


@wallace.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def summary(app):
    """Print a summary of a deployed app's status."""
    r = requests.get('https://{}.herokuapp.com/summary'.format(app))
    summary = r.json()['summary']
    print "\nstatus \t| count"
    print "----------------"
    for s in summary:
        print "{}\t| {}".format(s[0], s[1])
    num_101s = sum([s[1] for s in summary if s[0] == 101])
    num_10Xs = sum([s[1] for s in summary if s[0] >= 100])
    print "\nYield: {:.2%}".format(1.0*num_101s / num_10Xs)


@wallace.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
def debug(verbose):
    """Run the experiment locally."""
    (id, tmp) = setup(debug=True, verbose=verbose)

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
    os.rename("wallace_experiment.py", "wallace_experiment_tmp.py")
    with open("wallace_experiment_tmp.py", "r+") as f:
        with open("wallace_experiment.py", "w+") as f2:
            f2.write("from wallace.recruiters import HotAirRecruiter\n")
            for idx, line in enumerate(f):
                if re.search("\s*self.recruiter = (.*)", line):
                    p = line.partition("self.recruiter =")
                    f2.write(p[0] + p[1] + ' HotAirRecruiter\n')
                else:
                    f2.write(line)

    os.remove("wallace_experiment_tmp.py")

    # Set environment variables.
    aws_vars = ['aws_access_key_id', 'aws_secret_access_key', 'aws_region']
    for var in aws_vars:
        if var not in os.environ:
            os.environ[var] = config.get('AWS Access', var)

    pt_vars = ['psiturk_access_key_id', 'psiturk_secret_access_id']
    for var in pt_vars:
        if var not in os.environ:
            os.environ[var] = config.get('psiTurk Access', var)

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
        print "\nCouldn't open the psiTurk shell. Internet connection okay?"

    log("Completed debugging of experiment " + id + ".")
    os.chdir(cwd)


def deploy_sandbox_shared_setup(verbose=True, web_procs=1):
    """Set up Git, push to Heroku, and launch the app."""
    if verbose:
        OUT = None
    else:
        OUT = open(os.devnull, 'w')

    (id, tmp) = setup(debug=False, verbose=verbose)

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
        subprocess.call(cmd, stdout=OUT, shell=True)
        time.sleep(0.5)

    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    # Initialize the app on Heroku.
    log("Initializing app on Heroku...")
    subprocess.call(
        "heroku apps:create " + id +
        " --buildpack https://github.com/thenovices/heroku-buildpack-scipy",
        stdout=OUT,
        shell=True)

    database_size = config.get('Database Parameters', 'database_size')

    # Set up postgres database and AWS/psiTurk environment variables.
    cmds = [
        "heroku addons:create heroku-postgresql:{}".format(database_size),

        "heroku pg:wait",

        "heroku addons:create papertrail",

        "heroku config:set HOST=" +
        id + ".herokuapp.com",

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
    ]
    for cmd in cmds:
        subprocess.call(cmd + " --app " + id, stdout=OUT, shell=True)

    # Set the notification URL in the cofig file to the notifications URL.
    config.set(
        "Server Parameters",
        "notification_url",
        "http://" + id + ".herokuapp.com/notifications")

    # Set the database URL in the config file to the newly generated one.
    log("Saving the URL of the postgres database...")
    db_url = subprocess.check_output(
        "heroku config:get DATABASE_URL --app " + id, shell=True)
    config.set("Database Parameters", "database_url", db_url.rstrip())
    subprocess.call("git add config.txt", stdout=OUT, shell=True),
    time.sleep(0.25)
    subprocess.call(
        'git commit -m "Save URLs for database and notifications"',
        stdout=OUT,
        shell=True)
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    subprocess.call("git push heroku master", stdout=OUT,
                    stderr=OUT, shell=True)

    dyno_type = config.get('Server Parameters', 'dyno_type')
    num_dynos_web = config.get('Server Parameters', 'num_dynos_web')
    num_dynos_worker = config.get('Server Parameters', 'num_dynos_worker')

    log("Starting up the web server...")
    subprocess.call("heroku ps:scale web=" + str(num_dynos_web) + ":" +
                    str(dyno_type) + " --app " + id, stdout=OUT, shell=True)
    subprocess.call("heroku ps:scale worker=" + str(num_dynos_worker) + ":" +
                    str(dyno_type) + " --app " + id, stdout=OUT, shell=True)
    time.sleep(8)

    # Launch the experiment.
    log("Launching the experiment on MTurk...")
    subprocess.call(
        'curl --data "" http://{}.herokuapp.com/launch'.format(id),
        shell=True)

    time.sleep(8)

    url = subprocess.check_output("heroku logs --app " + id + " | sort | " +
                                  "sed -n 's|.*URL:||p'", shell=True)

    log("URLs:")
    print url

    # Return to the branch whence we came.
    os.chdir(cwd)

    log("Completed deployment of experiment " + id + ".")


@wallace.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
def sandbox(verbose):
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
    deploy_sandbox_shared_setup(verbose=verbose)


@wallace.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
def deploy(verbose):
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
    deploy_sandbox_shared_setup(verbose=verbose)


@wallace.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
@click.option(
    '--local', is_flag=True, flag_value=True, help='Export local data')
def export(app, local):
    """Export the data."""
    print_header()

    log("Preparing to export the data...")

    id = str(app)

    # Create the data package
    if not os.path.exists(id):
        os.makedirs(id)
    open(os.path.join(id, "README.txt"), "a").close()

    # Save the experiment id.
    with open(os.path.join(id, "experiment_id.txt"), "w") as file:
        file.write(id)

    if not local:
        # Export the logs
        subprocess.call(
            "heroku logs " +
            "-n 10000 > " + os.path.join(id, "server_logs.txt") +
            " --app " + id,
            shell=True)

        log("Generating a backup of the database on Heroku...")
        subprocess.call(
            "heroku pg:backups capture --app " + id, shell=True)
        # subprocess.call(
        #     "heroku pgbackups:capture --expire --app " + id, shell=True)
        backup_url = subprocess.check_output(
            "heroku pg:backups public-url --app " + id, shell=True)

        backup_url = backup_url.replace('"', '').rstrip()
        m = re.search("https:.*", backup_url)
        backup_url = m.group(0)

        log("Downloading the backup...")
        dump_filename = "data.dump"
        dump_path = os.path.join(id, dump_filename)
        with open(dump_path, 'wb') as file:
            subprocess.call(['curl', '-o', dump_path, backup_url], stdout=file)

        subprocess.call(
            "pg_restore --verbose --clean -d wallace " + id + "/data.dump",
            shell=True)

    data_directory = "data"
    os.makedirs(os.path.join(id, data_directory))

    all_tables = ["node",
                  "network",
                  "vector",
                  "info",
                  "transformation",
                  "transmission",
                  "psiturk",
                  "notification"]

    for table in all_tables:
        subprocess.call(
            "psql -d wallace --command=\"\\copy " + table + " to \'" +
            os.path.join(id, data_directory, table) + ".csv\' csv header\"",
            shell=True)

    if not local:
        os.remove(os.path.join(id, dump_filename))

    log("Zipping up the package...")
    shutil.make_archive(os.path.join("data", id + "-data"), "zip", id)

    shutil.rmtree(id)

    log("Done. Data available in " + str(id) + ".zip")


@wallace.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def logs(app):
    """Show the logs."""
    if app is None:
        raise TypeError("Select an experiment using the --app flag.")
    else:
        subprocess.call(
            "heroku addons:open papertrail --app " + app, shell=True)


@wallace.command()
@click.option('--example', default="bartlett1932", help='Name of the example')
def create(example):
    """Create a copy of the given example."""
    try:
        this_dir = os.path.dirname(os.path.realpath(__file__))
        example_dir = os.path.join(this_dir, os.pardir, "examples", example)
        shutil.copytree(example_dir, os.path.join(os.getcwd(), example))
        log("Example created.", delay=0)
    except TypeError:
        print "Example '{}' does not exist.".format(example)
    except OSError:
        print "Example '{}' already exists here.".format(example)


@wallace.command()
def verify():
    """Verify that app is compatible with Wallace."""
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

    return is_passing
