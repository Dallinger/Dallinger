#!/usr/bin/python
# -*- coding: utf-8 -*-

"""The Dallinger command-line utility."""

from __future__ import print_function
from __future__ import unicode_literals

import click
import os
import requests
import shutil
import signal
import sys
import tabulate
import time
import warnings
import webbrowser

from collections import Counter
from functools import wraps
from pathlib import Path
from rq import Worker, Connection
from sqlalchemy import exc as sa_exc


from dallinger.config import get_config
from dallinger import data
from dallinger import db
from dallinger.deployment import deploy_sandbox_shared_setup
from dallinger.deployment import DebugDeployment
from dallinger.deployment import LoaderDeployment
from dallinger.deployment import setup_experiment
from dallinger.command_line.develop import develop
from dallinger.command_line.docker import docker
from dallinger.command_line.docker_ssh import docker_ssh
from dallinger.notifications import admin_notifier
from dallinger.notifications import SMTPMailer
from dallinger.notifications import EmailConfig
from dallinger.notifications import MessengerError
from dallinger.heroku.tools import HerokuApp
from dallinger.heroku.tools import HerokuInfo
from dallinger.mturk import MTurkService
from dallinger.mturk import MTurkServiceException
from dallinger.recruiters import by_name
from dallinger.command_line.utils import Output
from dallinger.command_line.utils import header
from dallinger.command_line.utils import log
from dallinger.command_line.utils import require_exp_directory
from dallinger.command_line.utils import verify_package
from dallinger.command_line.utils import verify_id
from dallinger.utils import check_call
from dallinger.utils import ensure_constraints_file_presence
from dallinger.utils import generate_random_id
from dallinger.version import __version__


click.disable_unicode_literals_warning = True
warnings.simplefilter("ignore", category=sa_exc.SAWarning)


CONTEXT_SETTINGS = dict(help_option_names=["-h", "--help"])


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


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, "--version", "-v", message="%(version)s")
def dallinger():
    """Dallinger command-line utility."""
    from logging.config import fileConfig

    fileConfig(
        os.path.join(os.path.dirname(__file__), "..", "logging.ini"),
        disable_existing_loggers=False,
    )


dallinger.add_command(develop)
dallinger.add_command(docker)
dallinger.add_command(docker_ssh)


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
            os.path.dirname(os.path.realpath(__file__)),
            "..",
            "default_configs",
            config_name,
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


def prelaunch_db_bootstrapper(zip_path, log):
    def bootstrap_db(heroku_app, config):
        # Pre-populate the database if an archive was given
        log("Ingesting dataset from {}...".format(os.path.basename(zip_path)))
        engine = db.create_db_engine(heroku_app.db_url)
        data.bootstrap_db_from_zip(zip_path, engine)

    return bootstrap_db


def _deploy_in_mode(mode, verbose, log, app=None, archive=None):
    if app:
        verify_id(None, None, app)

    log(header, chevrons=False)
    prelaunch = []
    if archive:
        archive_path = os.path.abspath(archive)
        if not os.path.exists(archive_path):
            raise click.BadParameter(
                'Experiment archive "{}" does not exist.'.format(archive_path)
            )
        prelaunch.append(prelaunch_db_bootstrapper(archive_path, log))

    config = get_config()
    config.load()
    config.extend({"mode": mode, "logfile": "-"})

    deploy_sandbox_shared_setup(
        log=log, verbose=verbose, app=app, prelaunch_actions=prelaunch
    )


def fail_on_unsupported_urls(f):
    """raises click.UsageError if the current experiment has a dependecy using a git+ssh url,
    since they're not supported on Heroku without docker
    """

    @wraps(f)
    def wrapper(**kwargs):
        if "\ngit+ssh" in Path("requirements.txt").read_text():
            raise click.UsageError(
                "This experment has a git+ssh dependency.\n"
                "Dallinger does not support this for Heroku deployment using non-docker dynos.\n"
                "Try using the docker deployment by configuring a docker registry, adding the\n"
                "`docker_image_base_name` variable to config.txt and running\n"
                f"dallinger docker {f.__name__}"
            )
        return f(**kwargs)

    return wrapper


@dallinger.command()
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option("--app", default=None, help="Experiment id")
@click.option("--archive", default=None, help="Optional path to an experiment archive")
@require_exp_directory
@fail_on_unsupported_urls
@report_idle_after(21600)
def sandbox(verbose, app, archive):
    """Deploy app using Heroku to the MTurk Sandbox."""
    _deploy_in_mode(mode="sandbox", verbose=verbose, log=log, app=app, archive=archive)


@dallinger.command()
@click.option("--verbose", is_flag=True, flag_value=True, help="Verbose mode")
@click.option("--app", default=None, help="ID of the deployed experiment")
@click.option("--archive", default=None, help="Optional path to an experiment archive")
@require_exp_directory
@fail_on_unsupported_urls
@report_idle_after(21600)
def deploy(verbose, app, archive):
    """Deploy app using Heroku to MTurk."""
    _deploy_in_mode(mode="live", verbose=verbose, log=log, app=app, archive=archive)


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
    out.log("Email Config")
    out.log(tabulate.tabulate(settings.as_dict().items()), chevrons=False)
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
            )
            return

    out.log("HIT Details")
    out.log(tabulate.tabulate(result["hit"].items()), chevrons=False)
    out.log("Qualification Details")
    out.log(tabulate.tabulate(result["qualification"].items()), chevrons=False)
    out.log("Worker Notification")
    out.log(tabulate.tabulate(result["email"].items()), chevrons=False)


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
    if app is not None:
        return service.get_hits(hit_filter=lambda h: h.get("annotation") == app)
    return service.get_hits()


@dallinger.command()
@click.option("--app", default=None, help="Experiment id")
@click.option(
    "--sandbox",
    is_flag=True,
    flag_value=True,
    help="Look for HITs in the MTurk sandbox rather than the live/production environment",
)
def hits(app, sandbox):
    """List all HITs for the user's configured MTurk request account,
    or for a specific experiment id.
    """
    if app is not None:
        verify_id(None, "--app", app)
    formatted_hit_list = []
    dateformat = "%Y/%-m/%-d %I:%M:%S %p"
    for h in _current_hits(_mturk_service_from_config(sandbox), app):
        title = h["title"][:40] + "..." if len(h["title"]) > 40 else h["title"]
        description = (
            h["description"][:60] + "..."
            if len(h["description"]) > 60
            else h["description"]
        )
        formatted_hit_list.append(
            [
                h["id"],
                title,
                h["annotation"],
                h["status"],
                h["created"].strftime(dateformat),
                h["expiration"].strftime(dateformat),
                description,
            ]
        )
    out = Output()
    out.log("Found {} hit[s]:".format(len(formatted_hit_list)))
    out.log(
        tabulate.tabulate(
            formatted_hit_list,
            headers=[
                "Hit ID",
                "Title",
                "Annotation (experiment ID)",
                "Status",
                "Created",
                "Expiration",
                "Description",
            ],
        ),
        chevrons=False,
    )


@dallinger.command()
@click.option("--hit_id", default=None, help="MTurk HIT ID")
@click.option("--app", default=None, help="Experiment ID")
@click.option(
    "--sandbox",
    is_flag=True,
    flag_value=True,
    help="Look for HITs in the MTurk sandbox rather than the live/production environment",
)
def expire(hit_id, app, sandbox, exit=True):
    """Expire (set to "Reviewable") an MTurk HIT by specifying a HIT ID, or by
    specifying a Dallinger experiment ID, in which case HITs with the experiment
    ID in their ``annotation`` field will be expired.
    """
    if (hit_id and app) or not (hit_id or app):
        raise click.BadParameter("Must specify --hit_id or --app, but not both.")
    if app is not None:
        verify_id(None, "--app", app)
    service = _mturk_service_from_config(sandbox)

    # Assemble the list of HITs to expire
    if hit_id:
        targets = [hit_id]
    else:  # Find HITs based on --app value
        targets = [
            h["id"]
            for h in service.get_hits(hit_filter=lambda h: h.get("annotation") == app)
        ]

    success = []
    failures = []
    for hit_id in targets:
        try:
            service.expire_hit(hit_id=hit_id)
            success.append(hit_id)
        except MTurkServiceException:
            failures.append(hit_id)
    out = Output()
    if success:
        out.log(
            "Expired {} hit[s] (which may have already been expired): {}".format(
                len(success), ", ".join(success)
            )
        )
    if failures:
        out.log(
            "Could not expire {} hit[s]: {}".format(len(failures), ", ".join(failures))
        )
    if not success and not failures:
        out.error("Failed to find any matching HITs on MTurk.")
        if not sandbox:
            out.log(
                "If this experiment was run in the MTurk sandbox, use:\n"
                "  `dallinger expire --sandbox --app {}`".format(app),
                chevrons=False,
            )
        out.log("You can run `dallinger hits` to help troubleshoot.", chevrons=False)
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
            )
            return

    out.log("Updated HIT Details")
    out.log(tabulate.tabulate(hit_info.items()), chevrons=False)


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
@click.option(
    "--local",
    is_flag=True,
    flag_value=True,
    help="Only export data locally, skipping the Amazon S3 copy",
)
@click.option(
    "--no-scrub",
    is_flag=True,
    flag_value=True,
    help="Don't scrub PII (Personally Identifiable Information) - if not specified PII will be scrubbed",
)
def export(app, local, no_scrub):
    """Export the experiment data to a zip archive on your local computer, and
    by default, to Amazon S3."""
    log(header, chevrons=False)
    try:
        data.export(str(app), local=local, scrub_pii=(not no_scrub))
    except data.S3BucketUnavailable:
        log(
            "Your local export completed normally, but you don't have an "
            "Amazon S3 bucket accessible for a remote export. "
            "Either add an S3 bucket, or run with the --local option to "
            'avoid this warning. Run "dallinger export -h" for more details.'
        )


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
        verbose=verbose,
    )
    ok = verify_package(verbose=verbose)
    if ok:
        log("✓ Everything looks good!", verbose=verbose)
    else:
        log("☹ Some problems were found.", verbose=verbose)


@dallinger.command()
def rq_worker():
    """Start an rq worker in the context of dallinger."""
    setup_experiment(log)
    with Connection(db.redis_conn):
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


@dallinger.command()
@require_exp_directory
def generate_constraints():
    """Update an experiment's constraints.txt pinned dependencies based on requirements.txt."""
    experiment_dir = Path(os.getcwd())
    constraints_path = experiment_dir / "constraints.txt"
    if constraints_path.exists():
        constraints_path.unlink()
    ensure_constraints_file_presence(str(experiment_dir))


@click.group(context_settings=CONTEXT_SETTINGS)
@click.version_option(__version__, "--version", "-v", message="%(version)s")
def dallinger_housekeeper():
    """Dallinger utilities to do housekeeping in a dallinger environment."""
    from logging.config import fileConfig

    fileConfig(
        os.path.join(os.path.dirname(__file__), "..", "logging.ini"),
        disable_existing_loggers=False,
    )


@dallinger_housekeeper.command()
@click.option("--no-drop")
def initdb(no_drop):
    from dallinger.db import init_db

    drop_all = not no_drop
    init_db(drop_all=drop_all)
