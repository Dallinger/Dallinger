"""Miscellaneous tools for Heroku."""

import pexpect
import subprocess

from dallinger.config import get_config
from dallinger.compat import unicode


def app_name(id):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + id[0:8]


def auth_token():
    """A Heroku authenication token."""
    return unicode(subprocess.check_output(["heroku", "auth:token"]).rstrip())


def log_in():
    """Ensure that the user is logged in to Heroku."""
    p = pexpect.spawn("heroku auth:whoami")
    p.interact()


def scale_up_dynos(app):
    """Scale up the Heroku dynos."""
    config = get_config()
    if not config.ready:
        config.load()

    dyno_type = config.get('dyno_type')

    num_dynos = {
        "web": config.get('num_dynos_web'),
        "worker": config.get('num_dynos_worker'),
    }

    for process in ["web", "worker"]:
        subprocess.check_call([
            "heroku",
            "ps:scale",
            "{}={}:{}".format(process, num_dynos[process], dyno_type),
            "--app", app,
        ])

    if config.get('clock_on'):
        subprocess.check_call([
            "heroku",
            "ps:scale",
            "clock=1:{}".format(dyno_type),
            "--app", app,
        ])


def open_logs(app):
    """Show the logs."""
    if app is None:
        raise TypeError("Select an experiment using the --app flag.")
    else:
        subprocess.check_call([
            "heroku", "addons:open", "papertrail", "--app", app_name(app)
        ])
