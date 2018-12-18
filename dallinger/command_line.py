#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Dallinger command-line utility."""

from __future__ import print_function
from __future__ import unicode_literals

from collections import Counter
from functools import wraps
import inspect
import os
import shutil
import signal
import sys
import tabulate
import tempfile
import time
import webbrowser

import click
import requests
from rq import (
    Worker,
    Connection,
)

from dallinger.config import get_config
from dallinger.config import initialize_experiment_package
from dallinger import data
from dallinger.db import redis_conn
from dallinger.deployment import _deploy_in_mode
from dallinger.deployment import DebugDeployment
from dallinger.deployment import LoaderDeployment
from dallinger.deployment import setup_experiment
from dallinger.notifications import get_messenger
from dallinger.heroku.tools import HerokuApp
from dallinger.heroku.tools import HerokuInfo
from dallinger.mturk import MTurkService
from dallinger.mturk import MTurkServiceException
from dallinger.utils import check_call
from dallinger.utils import generate_random_id
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


class Output(object):

    def __init__(self, log=log, error=error, blather=sys.stdout.write):
        self.log = log
        self.error = error
        self.blather = blather


idle_template = """Dear experimenter,

This is an automated email from Dallinger. You are receiving this email because
your dyno has been running for over {minutes_so_far} minutes.

The application id is: {app_id}

To see the logs, use the command "dallinger logs --app {app_id}"
To pause the app, use the command "dallinger hibernate --app {app_id}"
To destroy the app, use the command "dallinger destroy --app {app_id}"


The Dallinger dev. team.
"""


def report_idle_after(seconds):
    """Report_idle_after after certain number of seconds."""
    def decorator(func):
        def wrapper(*args, **kwargs):
            def _handle_timeout(signum, frame):
                config = get_config()
                if not config.ready:
                    config.load()
                message = {
                    'subject': 'Idle Experiment.',
                    'body': idle_template.format(
                        app_id=config.get('id'),
                        minutes_so_far=round(seconds / 60)
                    )
                }
                log("Reporting problem with idle experiment...")
                get_messenger(config).send(message)

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


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--bot', is_flag=True, flag_value=True,
              help='Use bot to complete experiment')
@click.option('--proxy', default=None, help='Alternate port when opening browser windows')
def debug(verbose, bot, proxy, exp_config=None):
    """Run the experiment locally."""
    debugger = DebugDeployment(Output(), verbose, bot, proxy, exp_config)
    log(header, chevrons=False)
    debugger.run()


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
    if app:
        verify_id(None, None, app)
    log(header, chevrons=False)
    _deploy_in_mode('sandbox', app=app, verbose=verbose, log=log)


@dallinger.command()
@click.option('--verbose', is_flag=True, flag_value=True, help='Verbose mode')
@click.option('--app', default=None, help='ID of the deployed experiment')
@report_idle_after(21600)
def deploy(verbose, app):
    """Deploy app using Heroku to MTurk."""
    if app:
        verify_id(None, None, app)
    log(header, chevrons=False)
    _deploy_in_mode('live', app=app, verbose=verbose, log=log)


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
def expire(app, sandbox, exit=True):
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
    if exit and not success:
        sys.exit(1)


@dallinger.command()
@click.option('--app', default=None, callback=verify_id, help='Experiment id')
@click.confirmation_option(prompt='Are you sure you want to destroy the app?')
@click.option(
    '--expire-hit/--no-expire-hit', flag_value=True, default=True,
    prompt='Would you like to expire all MTurk HITs associated with this experiment id?',
    help='Expire any MTurk HITs associated with this experiment.')
@click.option('--sandbox', is_flag=True, flag_value=True,
              help='Is the app running in the sandbox?')
@click.pass_context
def destroy(ctx, app, expire_hit, sandbox):
    """Tear down an experiment server."""
    if expire_hit:
        ctx.invoke(expire, app=app, sandbox=sandbox, exit=False)
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
    log(header, chevrons=False)
    loader = LoaderDeployment(app, Output(), verbose, exp_config)
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

    (id, tmp) = setup_experiment(log)

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
    setup_experiment(log)
    with Connection(redis_conn):
        # right now we care about low queue for bots
        worker = Worker('low')
        worker.work()


@dallinger.command()
def apps():
    out = Output()
    config = get_config()
    if not config.ready:
        config.load()
    team = config.get("heroku_team", '').strip() or None
    command_runner = HerokuInfo(team=team)
    my_apps = command_runner.my_apps()
    my_user = command_runner.login_name()
    listing = []
    header_map = [
        {'title': 'UID', 'id': 'dallinger_uid'},
        {'title': 'Started', 'id': 'created_at'},
        {'title': 'URL', 'id': 'web_url'},
    ]
    headers = [h['title'] for h in header_map]
    for app in my_apps:
        app_info = []
        for detail in header_map:
            val = ''
            key = detail.get('id')
            if key:
                val = app.get(key, '')
            app_info.append(val)
        listing.append(app_info)
    if listing:
        out.log('Found {} heroku apps running for user {}'.format(
            len(listing), my_user
        ))
        out.log(tabulate.tabulate(listing, headers, tablefmt='psql'),
                chevrons=False)
    else:
        out.log('No heroku apps found for user {}'.format(my_user))
