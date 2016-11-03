"""Miscellaneous tools for Heroku."""

import pexpect


def app_name(id):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + id[0:8]


def log_in():
    """Ensure that the user is logged in to Heroku."""
    p = pexpect.spawn("heroku auth:whoami")
    p.interact()
