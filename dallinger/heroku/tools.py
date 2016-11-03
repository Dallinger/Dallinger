"""Miscellaneous tools for Heroku."""

import pexpect
from psiturk.psiturk_config import PsiturkConfig
import subprocess


def app_name(id):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + id[0:8]


def log_in():
    """Ensure that the user is logged in to Heroku."""
    p = pexpect.spawn("heroku auth:whoami")
    p.interact()


def scale_up_dynos(app):
    """Scale up the Heroku dynos."""
    # Load psiTurk configuration.
    config = PsiturkConfig()
    config.load_config()

    dyno_type = config.get('Server Parameters', 'dyno_type')
    num_dynos_web = config.get('Server Parameters', 'num_dynos_web')
    num_dynos_worker = config.get('Server Parameters', 'num_dynos_worker')

    subprocess.call(
        "heroku ps:scale web=" + str(num_dynos_web) + ":" +
        str(dyno_type) + " --app " + app, shell=True)

    subprocess.call(
        "heroku ps:scale worker=" + str(num_dynos_worker) + ":" +
        str(dyno_type) + " --app " + app, shell=True)

    clock_on = config.getboolean('Server Parameters', 'clock_on')
    if clock_on:
        subprocess.call(
            "heroku ps:scale clock=1:" + dyno_type + " --app " + app,
            shell=True)
