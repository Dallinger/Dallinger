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


@click.group()
def wallace():
    pass


def setup(debug=True):

    print_header()

    # Generate a unique id for this experiment.
    id = "w" + str(uuid.uuid4())[0:28]
    log("Debugging as experiment " + id + ".")

    # Create a git repository if one does not already exist.
    if not os.path.exists(".git"):
        log("No git repository detected; creating one.")
        cmds = ["git init",
                "git add .",
                'git commit -m "Experiment ' + id + '"']
        for cmd in cmds:
            subprocess.call(cmd, shell=True)
            time.sleep(0.5)

    # Create a new branch.
    log("Creating new branch and switching over to it...")
    starting_branch = subprocess.check_output(
        "git rev-parse --abbrev-ref HEAD", shell=True)
    subprocess.call("git branch " + id, shell=True)
    time.sleep(1)
    subprocess.call("git checkout " + id, shell=True)

    # Copy files into this experiment package.
    src = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "custom.py")
    dst = os.path.join(os.getcwd(), "custom.py")
    shutil.copy(src, dst)

    for filename in ["Procfile", "requirements.txt", "psiturkapp.py"]:
        src = os.path.join(
            os.path.dirname(os.path.realpath(__file__)),
            "heroku",
            filename)
        dst = os.path.join(os.getcwd(), filename)
        shutil.copy(src, dst)

    # Commit the new files to the new experiment branch.
    log("Inserting psiTurk- and Heroku-specfic files.")
    subprocess.call("git add .", shell=True),
    time.sleep(0.25)
    subprocess.call(
        'git commit -m "Insert psiTurk- and Heroku-specfic files"',
        shell=True)
    time.sleep(0.25)

    return (id, starting_branch)


@wallace.command()
def debug():
    """Run the experiment locally."""
    (id, starting_branch) = setup(debug=True)

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
    subprocess.call("dropdb " + database, shell=True)
    subprocess.call("psql --command=\"CREATE DATABASE " + database +
                    " WITH OWNER postgres;\"", shell=True)

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

    # Return to othe branch we came from.
    log("Cleaning up...")
    subprocess.call("git checkout " + starting_branch, shell=True)
    filetypes_to_kill = [".pyc", ".psiturk_history"]
    for filetype in filetypes_to_kill:
        [[os.remove(f) for f in os.listdir(".") if f.endswith(filetype)]
            for filetype in filetypes_to_kill]

    log("Completed debugging of experiment " + id)


@wallace.command()
def deploy():
    """Deploy app using Heroku."""
    (id, starting_branch) = setup(debug=False)

    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    # Initialize the app on Heroku.
    log("Initializing app on Heroku...")
    subprocess.call(
        "heroku apps:create " + id +
        " --buildpack https://github.com/thenovices/heroku-buildpack-scipy",
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
        subprocess.call(cmd + " --app " + id, shell=True)

    # Set the database URL in the config file to the newly generated one.
    log("Saving the URL of the postgres database...")
    db_url = subprocess.check_output(
        "heroku config:get DATABASE_URL --app " + id, shell=True)
    config.set("Database Parameters", "database_url", db_url.rstrip())
    subprocess.call("git add config.txt", shell=True),
    time.sleep(0.25)
    subprocess.call(
        'git commit -m "Save URL of Heroku postgres database"',
        shell=True)
    time.sleep(0.25)

    # Launch the Heroku app.
    log("Pushing code to Heroku...")
    subprocess.call("git push heroku " + id + ":master", shell=True)

    log("Starting up the web server...")
    subprocess.call("heroku ps:scale web=1 --app " + id, shell=True)
    time.sleep(8)
    subprocess.call("heroku restart --app " + id, shell=True)
    time.sleep(4)

    # Send launch signal to server.
    log("Launching the experiment...")
    url = "http://" + id + ".herokuapp.com/launch"
    print subprocess.call("curl -X POST " + url, shell=True)

    # Return to the branch we came from.
    log("Cleaning up...")
    subprocess.call("git checkout " + starting_branch, shell=True)

    log("Completed deployment of experiment " + id)


@wallace.command()
@click.option('--id', default=None, help='ID of the deployed experiment')
def export(id):
@wallace.command()
@click.option('--app', default=None, help='ID of the deployed experiment')
def export(app):
    """Export the data."""
    print_header()
    id = str(app)

    log("Preparing to export the data...")

    # Create the data package
    if not os.path.exists(id):
        os.makedirs(id)
    open(os.path.join(id, "README.txt"), "a").close()

    # Export the logs
    subprocess.call(
        "heroku logs " +
        "-n 10000 > " + os.path.join(id, "server_logs.txt") +
        " --app " + id,
        shell=True)

    # Save the experiment id.
    with open(os.path.join(id, "experiment_id.txt"), "w") as file:
        file.write(id)

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

    os.remove(os.path.join(id, dump_filename))

    log("Zipping up the package...")
    shutil.make_archive(id, "zip", id)
    shutil.rmtree(id)

    log("Done. Data available in " + str(id) + ".zip")
