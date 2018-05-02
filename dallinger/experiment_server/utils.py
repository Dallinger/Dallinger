import logging
from functools import update_wrapper
from flask import make_response


def nocache(func):
    """Stop caching for pages wrapped in nocache decorator."""
    def new_func(*args, **kwargs):
        """No cache Wrapper."""
        resp = make_response(func(*args, **kwargs))
        resp.cache_control.no_cache = True
        return resp
    return update_wrapper(new_func, func)


class LogLevels(object):

    def __init__(self, level):
        self._dlgr_level = level

    @property
    def pylog(self):
        levels = [
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL
        ]
        return levels[self._dlgr_level]

    @property
    def gunicorn(self):
        levels = ["debug", "info", "warning", "error", "critical"]
        return levels[self._dlgr_level]
