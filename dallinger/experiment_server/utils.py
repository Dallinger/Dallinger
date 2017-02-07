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
