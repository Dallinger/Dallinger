from __future__ import print_function
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
        if host.startswith('https://'):
            base_url = host
        elif host.startswith('http://'):
            base_url = host.replace('http://', 'https://')
        else:
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


def run_command(cmd, out):
    """We want to both send subprocess output to stdout or another file
    descriptor as the subprocess runs, *and* capture the actual exception
    message on errors. CalledProcessErrors do not reliably contain the
    underlying exception in either the 'message' or 'out' attributes, so
    when a CalledProcessError is raised, we re-run the command again with
    Popen(), which does return the error reliably.
    """
    try:
        subprocess.check_call(cmd, stdout=out, stderr=out)
    except subprocess.CalledProcessError:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        _, error = p.communicate()
        if p.returncode != 0:
            message = 'Command: "{}": Error: "{}"'.format(
                ' '.join(cmd), error.replace('\n', ''),
            )
            raise CommandError(message)


class CommandError(Exception):
    """Something went wrong executing a subprocess command"""


class GitError(Exception):
    """Something went wrong calling a Git command"""


class GitClient(object):
    """Minimal wrapper, mostly for mocking"""

    _sp_out = subprocess.PIPE

    def __init__(self, output=None):
        if output is None:
            self.out = sys.stdout
        else:
            self.out = output

    def init(self, config=None):
        self._run(["git", "init"])
        if config is not None:
            for k, v in config.items():
                self._run(["git", "config", k, v])

    def add(self, what):
        self._run(["git", "add", what])

    def commit(self, msg):
        self._run(["git", "commit", "-m", '"{}"'.format(msg)])

    def push(self, remote, branch):
        cmd = ["git", "push", remote, branch]
        self._run(cmd)

    def _run(self, cmd):
        self._log(cmd)
        try:
            run_command(cmd, self.out)
        except CommandError as e:
            raise GitError(e.message)

    def _log(self, cmd):
        print(
            '{}: "{}"'.format(self.__class__.__name__, ' '.join(cmd)),
            file=self.out
        )


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
