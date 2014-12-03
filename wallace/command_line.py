#!/usr/bin/python
# -*- coding: utf-8 -*-

import click
import time
import uuid
from psiturk.psiturk_config import PsiturkConfig
import os
import subprocess
import shutil
import pexpect
from urlparse import urlparse
import tempfile
import inspect
import imp
import pkg_resources


def log(msg, delay=0.5, chevrons=True):
    if chevrons:
        click.echo("\n❯❯ " + msg)
    else:
        click.echo(msg)
    time.sleep(delay)


def print_header():
    log("""
     _    _    __    __    __      __    ___  ____
    ( \/\/ )  /__\  (  )  (  )    /__\  / __)( ___)
     )    (  /(__)\  )(__  )(__  /(__)\ |(__  )__)
    (__/\__)(__)(__)(____)(____)(__)(__)\___)(____)

             a platform for experimental evolution.

    """, 0.5, False)


def printv(msg, verbose=False):
    if verbose:
        print msg


@click.group()
def wallace():
    pass


def setup(debug=True, verbose=False):

    print_header()

    if verbose:
        OUT = None
    else:
        OUT = open(os.devnull, 'w')

    # Verify that the package is usable.
    if not verify_package(verbose=verbose):
        raise AssertionError(
            "This is not a valid Wallace app. " +
            "Fix the errors and then try running 'wallace verify'.")

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

    # Create a git repository if one does not already exist.
    if not os.path.exists(".git"):
        log("No git repository detected; creating one...")
        cmds = ["git init",
                "git add .",
                'git commit -m "Experiment ' + id + '"']
        for cmd in cmds:
            subprocess.call(cmd, stdout=OUT, shell=True)
            time.sleep(0.5)

    # Create a new branch.
    log("Creating new branch and switching over to it...")
    starting_branch = subprocess.check_output(
        "git rev-parse --abbrev-ref HEAD", shell=True)
    subprocess.call("git branch " + id, stdout=OUT, shell=True)
    time.sleep(1)
    subprocess.call("git checkout " + id, stdout=OUT, stderr=OUT, shell=True)

    # Copy this directory into a temporary folder.
    dst = os.path.join(tempfile.mkdtemp(), id)
    shutil.copytree(os.getcwd(), dst)

    # Rename experiment.py to wallace_experiment.py to aviod psiTurk conflict.
    os.rename(
        os.path.join(dst, "experiment.py"),
        os.path.join(dst, "wallace_experiment.py"))

    # Copy files into this experiment package.
    src = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "custom.py")
    shutil.copy(src, os.path.join(dst, "custom.py"))

    for filename in ["Procfile", "requirements.txt", "psiturkapp.py"]:
        src = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "heroku",
            filename)
        shutil.copy(src, os.path.join(dst, filename))

    # Commit the new files to the new experiment branch.
    log("Inserting psiTurk- and Heroku-specfic files...")
    subprocess.call("git add .", stdout=OUT, shell=True),
    time.sleep(0.25)
    subprocess.call(
        'git commit -m "Insert psiTurk- and Heroku-specfic files"',
        stdout=OUT,
        shell=True)

    # Tag with the experiment name.
    name = config.get('Experiment Configuration', 'experiment')
    last_name = subprocess.check_output(
        "git tag | sort | tail -n 1", shell=True)
    if last_name:
        version = int(last_name.split("-")[-1]) + 1
    else:
        version = 1
    new_name = str(name) + "-" + str(version)
    subprocess.call("git tag " + new_name, stdout=OUT, shell=True)
    log("Tagging as experiment " + new_name + "...")

    time.sleep(0.25)

    return (id, starting_branch, dst)


@wallace.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
def debug(verbose):
    """Run the experiment locally."""
    if verbose:
        OUT = None
    else:
        OUT = open(os.devnull, 'w')

    (id, starting_branch, tmp) = setup(debug=True, verbose=verbose)

    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

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

    # Drop the testing database and recreate.
    log("Resetting the database...")
    result = urlparse(config.get("Database Parameters", "database_url"))
    database = result.path[1:]
    subprocess.call("dropdb " + database, stdout=OUT, shell=True)
    subprocess.call("psql --command=\"CREATE DATABASE " + database +
                    " WITH OWNER postgres;\"", stdout=OUT, shell=True)

    # Change to temporary directory.
    cwd = os.getcwd()
    os.chdir(tmp)

    # Start up the local server
    log("Starting up the server...")
    p = pexpect.spawn("psiturk")
    p.expect_exact("server")
    p.sendline("server on")

    # # Send launch signal to server.
    # log("Launching the experiment...")
    # host = config.get("Server Parameters", "host")
    # port = config.get("Server Parameters", "port")
    # url = "http://" + host + ":" + port + "/launch"
    # print subprocess.call("curl -X POST " + url, shell=True)

    log("Here's the psiTurk shell...")
    p.interact()

    # Return to the branch we came from.
    os.chdir(cwd)
    log("Cleaning up...")
    subprocess.call("git checkout " + starting_branch, shell=True)
    filetypes_to_kill = [".pyc", ".psiturk_history"]
    for filetype in filetypes_to_kill:
        [[os.remove(f) for f in os.listdir(".") if f.endswith(filetype)]
            for filetype in filetypes_to_kill]

    log("Completed debugging of experiment " + id + ".")


@wallace.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
def deploy(verbose):
    """Deploy app using Heroku."""

    if verbose:
        OUT = None
    else:
        OUT = open(os.devnull, 'w')

    (id, starting_branch, tmp) = setup(debug=False, verbose=verbose)

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

    # Set up postgres database and AWS/psiTurk environment variables.
    cmds = [
        "heroku addons:add heroku-postgresql:hobby-dev",

        "heroku pg:wait",

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
        config.get('psiTurk Access', 'psiturk_secret_access_id')
    ]
    for cmd in cmds:
        subprocess.call(cmd + " --app " + id, stdout=OUT, shell=True)

    # Set the database URL in the config file to the newly generated one.
    log("Saving the URL of the postgres database...")
    db_url = subprocess.check_output(
        "heroku config:get DATABASE_URL --app " + id, shell=True)
    config.set("Database Parameters", "database_url", db_url.rstrip())
    subprocess.call("git add config.txt", stdout=OUT, shell=True),
    time.sleep(0.25)
    subprocess.call(
        'git commit -m "Save URL of Heroku postgres database"',
        stdout=OUT,
        shell=True)
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    subprocess.call("git push heroku " + id + ":master", stdout=OUT,
                    stderr=OUT, shell=True)

    log("Starting up the web server...")
    subprocess.call(
        "heroku ps:scale web=1 --app " + id, stdout=OUT, shell=True)
    time.sleep(8)
    subprocess.call("heroku restart --app " + id, stdout=OUT, shell=True)
    time.sleep(4)

    # Send launch signal to server.
    log("Launching the experiment...")
    url = "http://" + id + ".herokuapp.com/launch"
    print subprocess.call("curl -X POST " + url,
                          stdout=OUT, stderr=OUT, shell=True)

    # Return to the branch we came from.
    log("Cleaning up...")
    subprocess.call("git checkout " + starting_branch,
                    stdout=OUT, stderr=OUT, shell=True)

    log("Completed deployment of experiment " + id + ".")

    os.chdir(cwd)


@wallace.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
@click.option(
    '--local', is_flag=True, flag_value=True, help='Export local data')
def export(app, local):
    """Export the data."""
    print_header()

    if app:
        all_tags = subprocess.check_output("git tag", shell=True).split("\n")
        if str(app) in all_tags:
            id = subprocess.check_output(
                "git rev-list " + str(app) + " | head -n 1", shell=True)
        else:
            id = str(app)
    else:
        id = subprocess.check_output(
            "git rev-parse --abbrev-ref HEAD", shell=True)

    log("Preparing to export the data...")

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
            "heroku addons:add pgbackups --app " + id, shell=True)
        subprocess.call(
            "heroku pgbackups:capture --expire --app " + id, shell=True)
        backup_url = subprocess.check_output(
            "heroku pgbackups:url --app " + id, shell=True)

        backup_url = backup_url.replace('"', '').rstrip()

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
                  "vector",
                  "info",
                  "transmission",
                  "agent",
                  "source",
                  "psiturk"]

    for table in all_tables:
        subprocess.call(
            "psql -d wallace --command=\"\\copy " + table + " to \'" +
            os.path.join(id, data_directory, table) + ".csv\' csv header\"",
            shell=True)

    if not local:
        os.remove(os.path.join(id, dump_filename))

    log("Zipping up the package...")
    shutil.make_archive(id, "zip", id)
    shutil.rmtree(id)

    log("Done. Data available in " + str(id) + ".zip")


@wallace.command()
@click.option('--example', default="bartlett1932", help='Name of the example')
def create(example):
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
    verify_package(verbose=True)


def verify_package(verbose=True):

    is_passing = True

    # Check the config file.
    if os.path.exists("config.txt"):
        printv("✓ config.txt is OK", verbose=verbose)
    else:
        printv("✗ config.txt is MISSING", verbose=verbose)
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
            printv(
                "✗ experiment.py does not define an experiment class.",
                verbose=verbose)
            is_passing = False
        elif len(exps) == 1:
            printv("✓ experiment.py is OK", verbose=verbose)
        else:
            printv(
                "✗ experiment.py defines more than one experiment class.",
                verbose=verbose)
        os.chdir(cwd)

    else:
        printv("✗ experiment.py is MISSING", verbose=verbose)
        is_passing = False

    # Make sure there's a help file.
    is_txt_readme = os.path.exists("README.md")
    is_md_readme = os.path.exists("README.txt")
    if (not is_md_readme) and (not is_txt_readme):
        is_passing = False
        printv("✗ README.txt or README.md is MISSING.", verbose=verbose)
    else:
        printv("✓ README is OK", verbose=verbose)

    return is_passing
