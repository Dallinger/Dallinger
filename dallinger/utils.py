from dallinger.config import get_config
import functools
import io
import os
import random
import string
import subprocess
import sys
import tempfile


def get_base_url():
    config = get_config()
    host = os.getenv('HOST', config.get('host'))
    if 'herokuapp.com' in host:
        base_url = "https://{}".format(host)
    else:
        # debug mode
        base_port = config.get('base_port')
        port_range = range(base_port, base_port + config.get('num_dynos_web', 1))
        base_url = "http://{}:{}".format(host, random.choice(port_range))

    return base_url


def generate_random_id(size=6, chars=string.ascii_uppercase + string.digits):
    """Generate random id numbers."""
    return ''.join(random.choice(chars) for x in range(size))


def wrap_subprocess_call(func, wrap_stdout=True):
    @functools.wraps(func)
    def wrapper(*popenargs, **kwargs):
        out = kwargs.get('stdout', None)
        err = kwargs.get('stderr', None)
        replay_out = False
        replay_err = False
        if out is None and wrap_stdout:
            try:
                sys.stdout.fileno()
            except io.UnsupportedOperation:
                kwargs['stdout'] = tempfile.NamedTemporaryFile()
                replay_out = True
        if err is None:
            try:
                sys.stderr.fileno()
            except io.UnsupportedOperation:
                kwargs['stderr'] = tempfile.NamedTemporaryFile()
                replay_err = True
        try:
            return func(*popenargs, **kwargs)
        finally:
            if replay_out:
                kwargs['stdout'].seek(0)
                sys.stdout.write(kwargs['stdout'].read())
            if replay_err:
                kwargs['stderr'].seek(0)
                sys.stderr.write(kwargs['stderr'].read())
    return wrapper


check_call = wrap_subprocess_call(subprocess.check_call)
call = wrap_subprocess_call(subprocess.call)
check_output = wrap_subprocess_call(subprocess.check_output, wrap_stdout=False)
