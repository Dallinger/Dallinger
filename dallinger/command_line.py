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
from rq import Worker, Connection

from dallinger.config import get_config
from dallinger.config import initialize_experiment_package
from dallinger import data
from dallinger.db import redis_conn
from dallinger.deployment import _deploy_in_mode
from dallinger.deployment import DebugDeployment
from dallinger.deployment import LoaderDeployment
from dallinger.deployment import setup_experiment
from dallinger.deployment import ExperimentFileSource
from dallinger.notifications import admin_notifier
from dallinger.notifications import SMTPMailer
from dallinger.notifications import EmailConfig
from dallinger.notifications import MessengerError
from dallinger.heroku.tools import HerokuApp
from dallinger.heroku.tools import HerokuInfo
from dallinger.mturk import MTurkService
from dallinger.mturk import MTurkServiceException
from dallinger.recruiters import by_name
from dallinger.utils import check_call
from dallinger.utils import generate_random_id
from dallinger.version import __version__

CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])

header = r"""
    ____        ____
   / __ \____ _/ / (_)___  ____ ____  _____
  / / / / __ `/ / / / __ \/ __ `/ _ \/ ___/
 / /_/ / /_/ / / / / / / / /_/ /  __/ /
/_____/\__,_/_/_/_/_/ /_/\__, /\___/_/
                        /____/
                                 {:>8}

                Laboratory automation for
       the behavioral and social sciences.
""".format(
    "v" + __version__
)


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
            click.secho("\n❯❯ " + msg, err=True, fg="red")
        else:
            click.secho(msg, err=True, fg="red")
        time.sleep(delay)


class Output(object):
    def __init__(self, log=log, error=error, blather=None):
        self.log = log
        self.error = error
        if blather is None:
            blather = sys.stdout.write
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
                    "subject": "Idle Experiment.",
                    "body": idle_template.format(
                        app_id=config.get("id"), minutes_so_far=round(seconds / 60)
                    ),
                }
                log("Reporting problem with idle experiment...")
                admin_notifier(config).send(**message)

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
        raise TypeError("Select an experiment using the --app parameter.")
    elif app[0:5] == "dlgr-":
        raise ValueError(
            "The --app parameter requires the full "
            "UUID beginning with {}-...".format(app[5:13])
        )
    return app


def verify_directory(verbose=True, max_size_mb=50):
    """Ensure that the current directory looks like a Dallinger experiment, and
    does not appear to have unintended contents that will be copied on
    deployment.
    """
    # Check required files
    ok = True
    mb_to_bytes = 1000 * 1000
    expected_files = ["config.txt", "experiment.py"]

    for f in expected_files:
        if os.path.exists(f):
            log("✓ {} is PRESENT".format(f), chevrons=False, verbose=verbose)
        else:
            log("✗ {} is MISSING".format(f), chevrons=False, verbose=verbose)
            ok = False

    # Check size
    max_size = max_size_mb * mb_to_bytes
    file_source = ExperimentFileSource(os.getcwd())
    size = file_source.size
    if size > max_size:
        size_in_mb = round(size / mb_to_bytes)
        log(
            "✗ {}MB is TOO BIG (greater than {}MB)\n\tIncluded files:\n\t{}".format(
                size_in_mb, max_size_mb, "\n\t".join(file_source.files)
            ),
            chevrons=False,
            verbose=verbose,
        )
        ok = False

    return ok


def verify_experiment_module(verbose):
    """Perform basic sanity checks on experiment.py.
    """
    ok = True
    if not os.path.exists("experiment.py"):
        return False

    # Bootstrap a package in a temp directory and make it importable:
    temp_package_name = "TEMP_VERIFICATION_PACKAGE"
    tmp = tempfile.mkdtemp()
    clone_dir = os.path.join(tmp, temp_package_name)
    to_ignore = shutil.ignore_patterns(
        os.path.join(".git", "*"), "*.db", "snapshots", "data", "server.log"
    )
    shutil.copytree(os.getcwd(), clone_dir, ignore=to_ignore)
    initialize_experiment_package(clone_dir)
    from dallinger_experiment import experiment

    if clone_dir not in experiment.__file__:
        raise ImportError("Checking the wrong experiment.py... aborting.")
    classes = inspect.getmembers(experiment, inspect.isclass)
    exps = [c for c in classes if (c[1].__bases__[0].__name__ in "Experiment")]

    # Clean up:
    for entry in [k for k in sys.modules if temp_package_name in k]:
        del sys.modules[entry]

    # Run checks:
    if len(exps) == 0:
        log(
            "✗ experiment.py does not define an experiment class.",
            delay=0,
            chevrons=False,
            verbose=verbose,
        )
        ok = False
    elif len(exps) == 1:
        log(
            "✓ experiment.py defines 1 experiment",
            delay=0,
            chevrons=False,
            verbose=verbose,
        )
    else:
        log(
            "✗ experiment.py defines more than one experiment class.",
            delay=0,
            chevrons=False,
            verbose=verbose,
        )
        ok = False

    return ok


def verify_config(verbose=True):
    """Check for common or costly errors in experiment configuration.
    """
    ok = True
    config = get_config()
    if not config.ready:
        try:
            config.load()
        except ValueError as e:
            config_key = getattr(e, "dallinger_config_key", None)
            if config_key is not None:
                message = "Configuration for {} is invalid: ".format(config_key)
            else:
                message = "Configuration is invalid: "
            log("✗ " + message + str(e), delay=0, chevrons=False, verbose=verbose)

            config_value = getattr(e, "dallinger_config_value", None)
            if verbose and config_value:
                log("  Value supplied was " + config_value, chevrons=False)
            return False
    # Check base_payment is correct
    try:
        base_pay = config.get("base_payment")
    except KeyError:
        log("✗ No value for base_pay.", delay=0, chevrons=False, verbose=verbose)
    else:
        dollarFormat = "{:.2f}".format(base_pay)

        if base_pay <= 0:
            log(
                "✗ base_payment must be positive value in config.txt.",
                delay=0,
                chevrons=False,
                verbose=verbose,
            )
            ok = False

        if float(dollarFormat) != float(base_pay):
            log(
                "✗ base_payment must be in [dollars].[cents] format in config.txt. Try changing "
                "{0} to {1}.".format(base_pay, dollarFormat),
                delay=0,
                chevrons=False,
                verbose=verbose,
            )
            ok = False

    return ok


def verify_no_conflicts(verbose=True):
    """Warn if there are filenames which conflict with those deployed by
    Dallinger, but always returns True (meaning "OK").
    """
    conflicts = False

    reserved_files = [
        os.path.join("templates", "complete.html"),
        os.path.join("templates", "error.html"),
        os.path.join("templates", "error-complete.html"),
        os.path.join("templates", "launch.html"),
        os.path.join("templates", "thanks.html"),
        os.path.join("static", "css", "dallinger.css"),
        os.path.join("static", "scripts", "dallinger2.js"),
        os.path.join("static", "scripts", "reqwest.min.js"),
        os.path.join("static", "scripts", "store+json2.min.js"),
        os.path.join("static", "scripts", "tracker.js"),
        os.path.join("static", "robots.txt"),
    ]

    for f in reserved_files:
        if os.path.exists(f):
            log(
                "✗ {} OVERWRITES shared frontend files inserted at run-time".format(f),
                delay=0,
                chevrons=False,
                verbose=verbose,
            )
            conflicts = True

    if not conflicts:
        log("✓ no file conflicts", delay=0, chevrons=False, verbose=verbose)

    return True


def verify_package(verbose=True):
    """Perform a series of checks on the current directory to verify that
    it's a valid Dallinger experiment.
    """
    results = (
        verify_directory(verbose),
        verify_experiment_module(verbose),
        verify_config(verbose),
        verify_no_conflicts(verbose),
    )

    ok = all(results)

    return ok


def require_exp_directory(f):
    """Decorator to verify that a command is run inside a valid Dallinger
    experiment directory.
    """
    error_one = "The current directory is not a valid Dallinger experiment."
    error_two = "There are problems with the current experiment. Please check with dallinger verify."

    @wraps(f)
    def wrapper(**kwargs):
        try:
            if not verify_package(kwargs.get("verbose")):
                raise click.UsageError(error_one)
        except ValueError:
            raise click.UsageError(error_two)
        return f(**kwargs)

    return wrapper


click.disable_unicode_literals_warning = True


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, "--version", "-v", message="%(version)s")
def dallinger():
    """Dallinger command-line utility."""
    from logging.config import fileConfig

    fileConfig(
        os.path.join(os.path.dirname(__file__), "logging.ini"),
        disable_existing_loggers=False,
    )


@dallinger.command()
def setup():
    """Walk the user though the Dallinger setup."""
    # Create the Dallinger config file if it does not already exist.
    config_name = ".dallingerconfig"
    config_path = os.path.join(os.path.expanduser("~"), config_name)

    if os.path.isfile(config_path):
        log("Dallinger config file already exists.", chevrons=False)

    else:
        log("Creating Dallinger config file at ~/.dallingerconfig...", chevrons=False)
        src = os.path.join(
            os.path.dirname(os.path.realpath(__file__)), "default_configs", config_name
        )
        shutil.copyfile(src, config_path)


@dallinger.command()
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
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
    r = requests.get("{}/summary".format(heroku_app.url))
    summary = r.json()["summary"]
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
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option(
    "--bot", is_flag=True, flag_value=True, help="Use bot to complete experiment"
)
@click.option(
    "--proxy", default=None, help="Alternate port when opening browser windows"
)
@click.option(
    "--no-browsers",
    is_flag=True,
    flag_value=True,
    default=False,
    help="Skip opening browsers",
)
@require_exp_directory
def debug(verbose, bot, proxy, no_browsers=False, exp_config=None):
    """Run the experiment locally."""
    debugger = DebugDeployment(Output(), verbose, bot, proxy, exp_config, no_browsers)
    log(header, chevrons=False)
    debugger.run()


def _mturk_service_from_config(sandbox):
    config = get_config()
    config.load()
    return MTurkService(
        aws_access_key_id=config.get("aws_access_key_id"),
        aws_secret_access_key=config.get("aws_secret_access_key"),
        region_name=config.get("aws_region"),
        sandbox=sandbox,
    )


@dallinger.command()
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option("--app", default=None, help="Experiment id")
@require_exp_directory
@report_idle_after(21600)
def sandbox(verbose, app):
    """Deploy app using Heroku to the MTurk Sandbox."""
    if app:
        verify_id(None, None, app)
    log(header, chevrons=False)
    _deploy_in_mode("sandbox", app=app, verbose=verbose, log=log)


@dallinger.command()
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option("--app", default=None, help="ID of the deployed experiment")
@require_exp_directory
@report_idle_after(21600)
def deploy(verbose, app):
    """Deploy app using Heroku to MTurk."""
    if app:
        verify_id(None, None, app)
    log(header, chevrons=False)
    _deploy_in_mode("live", app=app, verbose=verbose, log=log)


@dallinger.command()
@click.option("--qualification")
@click.option("--value")
@click.option(
    "--by_name",
    is_flag=True,
    flag_value=True,
    help="Use a qualification name, not an ID",
)
@click.option("--notify", is_flag=True, flag_value=True, help="Notify worker by email")
@click.option("--sandbox", is_flag=True, flag_value=True, help="Use the MTurk sandbox")
@click.argument("workers", nargs=-1)
def qualify(workers, qualification, value, by_name, notify, sandbox):
    """Assign a qualification to 1 or more workers"""
    if not (workers and qualification and value):
        raise click.BadParameter(
            "Must specify a qualification ID, value/score, and at least one worker ID"
        )
    mturk = _mturk_service_from_config(sandbox)
    if by_name:
        result = mturk.get_qualification_type_by_name(qualification)
        if result is None:
            raise click.BadParameter(
                'No qualification with name "{}" exists.'.format(qualification)
            )

        qid = result["id"]
    else:
        qid = qualification

    click.echo(
        "Assigning qualification {} with value {} to {} worker{}...".format(
            qid, value, len(workers), "s" if len(workers) > 1 else ""
        )
    )
    for worker in workers:
        if mturk.assign_qualification(qid, worker, int(value), notify=notify):
            click.echo("{} OK".format(worker))

    # print out the current set of workers with the qualification
    results = list(mturk.get_workers_with_qualification(qid))

    click.echo("{} workers with qualification {}:".format(len(results), qid))

    for score, count in Counter([r["score"] for r in results]).items():
        click.echo("{} with value {}".format(count, score))


@dallinger.command()
def email_test():
    """Test email configuration and send a test email."""
    out = Output()
    config = get_config()
    config.load()
    settings = EmailConfig(config)
    out.log("Email Config", delay=0)
    out.log(tabulate.tabulate(settings.as_dict().items()), chevrons=False, delay=0)
    problems = settings.validate()
    if problems:
        out.error(
            "✗ There are mail configuration problems. Fix these first:\n{}".format(
                problems
            )
        )
        return

    else:
        out.log("✓ email config looks good!")
    mailer = SMTPMailer(
        config.get("smtp_host"),
        config.get("smtp_username"),
        config.get("smtp_password"),
    )
    msg = {
        "subject": "Test message from Dallinger",
        "sender": config.get("dallinger_email_address"),
        "recipients": [config.get("contact_email_on_error")],
        "body": "This has been a test...",
    }
    out.log("Sending a test email from {sender} to {recipients[0]}".format(**msg))
    try:
        mailer.send(**msg)
    except MessengerError:
        out.error("✗ Message sending failed...")
        raise
    else:
        out.log("✓ Test email sent successfully to {}!".format(msg["recipients"][0]))


@dallinger.command()
@click.option("--recruiter", default="mturk", required=True)
@click.option("--worker_id", required=True)
@click.option("--email")
@click.option("--dollars", required=True, type=float)
@click.option("--sandbox", is_flag=True, flag_value=True, help="Use the MTurk sandbox")
def compensate(recruiter, worker_id, email, dollars, sandbox):
    """Credit a specific worker by ID through their recruiter"""
    out = Output()
    config = get_config()
    config.load()
    mode = "sandbox" if sandbox else "live"
    do_notify = email is not None
    no_email_str = "" if email else " NOT"

    with config.override({"mode": mode}):
        rec = by_name(recruiter)
        if not click.confirm(
            '\n\nYou are about to pay worker "{}" ${:.2f} in "{}" mode using the "{}" recruiter.\n'
            "The worker will{} be notified by email. "
            "Continue?".format(worker_id, dollars, mode, recruiter, no_email_str)
        ):
            out.log("Aborting...")
            return

        try:
            result = rec.compensate_worker(
                worker_id=worker_id, email=email, dollars=dollars, notify=do_notify
            )
        except Exception as ex:
            out.error(
                "Compensation failed. The recruiter reports the following error:\n{}".format(
                    ex
                ),
                delay=0,
            )
            return

    out.log("HIT Details", delay=0)
    out.log(tabulate.tabulate(result["hit"].items()), chevrons=False, delay=0)
    out.log("Qualification Details", delay=0)
    out.log(tabulate.tabulate(result["qualification"].items()), chevrons=False, delay=0)
    out.log("Worker Notification", delay=0)
    out.log(tabulate.tabulate(result["email"].items()), chevrons=False, delay=0)


@dallinger.command()
@click.option("--qualification")
@click.option(
    "--by_name",
    is_flag=True,
    flag_value=True,
    help="Use a qualification name, not an ID",
)
@click.option(
    "--reason",
    default="Revoking automatically assigned Dallinger qualification",
    help="Reason for revoking qualification",
)
@click.option("--sandbox", is_flag=True, flag_value=True, help="Use the MTurk sandbox")
@click.argument("workers", nargs=-1)
def revoke(workers, qualification, by_name, reason, sandbox):
    """Revoke a qualification from 1 or more workers"""
    if not (workers and qualification):
        raise click.BadParameter(
            "Must specify a qualification ID or name, and at least one worker ID"
        )

    mturk = _mturk_service_from_config(sandbox)
    if by_name:
        result = mturk.get_qualification_type_by_name(qualification)
        if result is None:
            raise click.BadParameter(
                'No qualification with name "{}" exists.'.format(qualification)
            )

        qid = result["id"]
    else:
        qid = qualification

    if not click.confirm(
        '\n\nYou are about to revoke qualification "{}" '
        "for these workers:\n\t{}\n\n"
        "This will send an email to each of them from Amazon MTurk. "
        "Continue?".format(qid, "\n\t".join(workers))
    ):
        click.echo("Aborting...")
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
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
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
    return service.get_hits(hit_filter=lambda h: h.get("annotation") == app)


@dallinger.command()
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
@click.option(
    "--sandbox",
    is_flag=True,
    flag_value=True,
    help="Is the app running in the sandbox?",
)
def hits(app, sandbox):
    """List hits for an experiment id."""
    hit_list = list(_current_hits(_mturk_service_from_config(sandbox), app))
    out = Output()
    out.log(
        "Found {} hits for this experiment id: {}".format(
            len(hit_list), ", ".join(h["id"] for h in hit_list)
        )
    )


@dallinger.command()
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
@click.option(
    "--sandbox",
    is_flag=True,
    flag_value=True,
    help="Is the app running in the sandbox?",
)
def expire(app, sandbox, exit=True):
    """Expire hits for an experiment id."""
    success = []
    failures = []
    service = _mturk_service_from_config(sandbox)
    hits = _current_hits(service, app)
    for hit in hits:
        hit_id = hit["id"]
        try:
            service.expire_hit(hit_id=hit_id)
            success.append(hit_id)
        except MTurkServiceException:
            failures.append(hit_id)
    out = Output()
    if success:
        out.log("Expired {} hits: {}".format(len(success), ", ".join(success)))
    if failures:
        out.log(
            "Could not expire {} hits: {}".format(len(failures), ", ".join(failures))
        )
    if not success and not failures:
        out.log("No hits found for this application.")
        if not sandbox:
            out.log(
                "If this experiment was run in the MTurk sandbox, use: "
                "`dallinger expire --sandbox --app {}`".format(app)
            )
    if exit and not success:
        sys.exit(1)


@dallinger.command()
@click.option("--hit_id", required=True)
@click.option("--assignments", required=True, type=int)
@click.option("--duration_hours", type=float)
@click.option(
    "--sandbox", is_flag=True, flag_value=True, help="HIT is in the MTurk sandbox"
)
def extend_mturk_hit(hit_id, assignments, duration_hours, sandbox):
    """Add assignments, and optionally time, to an existing MTurk HIT."""
    out = Output()
    config = get_config()
    config.load()
    mode = "sandbox" if sandbox else "live"
    assignments_presented = "assignments" if assignments > 1 else "assignment"
    duration_presented = duration_hours or 0.0

    with config.override({"mode": mode}):
        if not click.confirm(
            "\n\nYou are about to add {:.1f} hours and {} {} to {} HIT {}.\n"
            "Continue?".format(
                duration_presented, assignments, assignments_presented, mode, hit_id
            )
        ):
            out.log("Aborting...")
            return

        service = _mturk_service_from_config(sandbox)
        try:
            hit_info = service.extend_hit(
                hit_id=hit_id, number=assignments, duration_hours=duration_hours
            )
        except MTurkServiceException as ex:
            out.error(
                "HIT extension failed with the following error:\n{}".format(ex),
                delay=0,
            )
            return

    out.log("Updated HIT Details", delay=0)
    out.log(tabulate.tabulate(hit_info.items()), chevrons=False, delay=0)


@dallinger.command()
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
@click.confirmation_option(prompt="Are you sure you want to destroy the app?")
@click.option(
    "--expire-hit/--no-expire-hit",
    flag_value=True,
    default=True,
    prompt="Would you like to expire all MTurk HITs associated with this experiment id?",
    help="Expire any MTurk HITs associated with this experiment.",
)
@click.option(
    "--sandbox",
    is_flag=True,
    flag_value=True,
    help="Is the app running in the sandbox?",
)
@click.pass_context
def destroy(ctx, app, expire_hit, sandbox):
    """Tear down an experiment server."""
    if expire_hit:
        ctx.invoke(expire, app=app, sandbox=sandbox, exit=False)
    HerokuApp(app).destroy()


@dallinger.command()
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
@click.option("--databaseurl", default=None, help="URL of the database")
def awaken(app, databaseurl):
    """Restore the database from a given url."""
    id = app
    config = get_config()
    config.load()

    bucket = data.user_s3_bucket()
    key = bucket.lookup("{}.dump".format(id))
    url = key.generate_url(expires_in=300)

    heroku_app = HerokuApp(id, output=None, team=None)
    heroku_app.addon("heroku-postgresql:{}".format(config.get("database_size")))
    time.sleep(60)

    heroku_app.pg_wait()
    time.sleep(10)

    heroku_app.addon("heroku-redis:{}".format(config.get("redis_size")))
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
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
@click.option("--local", is_flag=True, flag_value=True, help="Export local data")
@click.option("--no-scrub", is_flag=True, flag_value=True, help="Scrub PII")
def export(app, local, no_scrub):
    """Export the data."""
    log(header, chevrons=False)
    data.export(str(app), local=local, scrub_pii=(not no_scrub))


@dallinger.command()
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option("--replay", is_flag=True, flag_value=True, help="Replay mode")
def load(app, verbose, replay, exp_config=None):
    """Import database state from an exported zip file and leave the server
    running until stopping the process with <control>-c.
    """
    if replay:
        exp_config = exp_config or {}
        exp_config["replay"] = True
    log(header, chevrons=False)
    loader = LoaderDeployment(app, Output(), verbose, exp_config)
    loader.run()


@dallinger.command()
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
def logs(app):
    """Show the logs."""
    if app is None:
        raise TypeError("Select an experiment using the --app parameter.")

    HerokuApp(dallinger_uid=app).open_logs()


@dallinger.command()
@click.option("--app", default=None, callback=verify_id, help="Experiment id")
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
@click.option("--app", default=None, help="Experiment id")
@click.option("--debug", default=None, help="Local debug recruitment url")
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
        ad_url = "{}/ad".format(heroku_app.url)
        ad_parameters = "assignmentId={}&hitId={}&workerId={}&mode=sandbox"
        ad_parameters = ad_parameters.format(assignment, hit, worker)
        url = "{}?{}".format(ad_url, ad_parameters)
    bot = bot_factory(url)
    bot.run_experiment()


@dallinger.command()
def verify():
    """Verify that app is compatible with Dallinger."""
    verbose = True
    log(
        "Verifying current directory as a Dallinger experiment...",
        delay=0,
        verbose=verbose,
    )
    ok = verify_package(verbose=verbose)
    if ok:
        log("✓ Everything looks good!", delay=0, verbose=verbose)
    else:
        log("☹ Some problems were found.", delay=0, verbose=verbose)


@dallinger.command()
def rq_worker():
    """Start an rq worker in the context of dallinger."""
    setup_experiment(log)
    with Connection(redis_conn):
        # right now we care about low queue for bots
        worker = Worker("low")
        worker.work()


@dallinger.command()
def apps():
    out = Output()
    config = get_config()
    if not config.ready:
        config.load()
    team = config.get("heroku_team", None)
    command_runner = HerokuInfo(team=team)
    my_apps = command_runner.my_apps()
    my_user = command_runner.login_name()
    listing = []
    header_map = [
        {"title": "UID", "id": "dallinger_uid"},
        {"title": "Started", "id": "created_at"},
        {"title": "URL", "id": "web_url"},
    ]
    headers = [h["title"] for h in header_map]
    for app in my_apps:
        app_info = []
        for detail in header_map:
            val = ""
            key = detail.get("id")
            if key:
                val = app.get(key, "")
            app_info.append(val)
        listing.append(app_info)
    if listing:
        out.log(
            "Found {} heroku apps running for user {}".format(len(listing), my_user)
        )
        out.log(tabulate.tabulate(listing, headers, tablefmt="psql"), chevrons=False)
    else:
        out.log("No heroku apps found for user {}".format(my_user))
