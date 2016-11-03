"""Miscellaneous tools for Heroku."""

def app_name(id):
    """Convert a UUID to a valid Heroku app name."""
    return "dlgr-" + id[0:8]
