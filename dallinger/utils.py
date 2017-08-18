from dallinger.config import get_config
import os
import random
import string
import subprocess


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


class GitClient(object):
    """Minimal wrapper, mostly for mocking"""

    def __init__(self, output):
        self.out = output

    def init(self):
        subprocess.check_call(["git", "init"], stdout=self.out)

    def add(self, what):
        subprocess.check_call(["git", "add", what])

    def commit(self, msg):
        subprocess.check_call(["git", "commit", "-m", '"{}"'.format(msg)])

    def push(self, remote, branch):
        cmd = ["git", "push", remote, branch]
        subprocess.check_call(cmd, stdout=self.out, stderr=self.out)
