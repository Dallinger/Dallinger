"""Miscellaneous tools for Heroku."""

import pexpect
import subprocess

import dallinger as dlgr


def app_name(id):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + id[0:8]


def log_in():
    """Ensure that the user is logged in to Heroku."""
    p = pexpect.spawn("heroku auth:whoami")
    p.interact()


def scale_up_dynos(app):
    """Scale up the Heroku dynos."""
    dyno_type = dlgr.config.server_parameters.dyno_type

    num_dynos = {
        "web": dlgr.config.server_parameters.num_dynos_web,
        "worker": dlgr.config.server_parameters.num_dynos_worker
    }

    for process in ["web", "worker"]:
        subprocess.check_call([
            "heroku",
            "ps:scale",
            "{}={}:{}".format(process, num_dynos[process], dyno_type),
            "--app",
            app,
        ])

    if dlgr.config.server_parameters.clock_on:
        subprocess.check_call([
            "heroku",
            "ps:scale",
            "clock=1:{}".format(dyno_type),
            "--app",
            app,
        ])
