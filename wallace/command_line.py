#!/usr/bin/python
# -*- coding: utf-8 -*-

import optparse
import uuid
import os
import shutil
from psiturk.psiturk_config import PsiturkConfig
# import pexpect

print """
     _    _    __    __    __      __    ___  ____
    ( \/\/ )  /__\  (  )  (  )    /__\  / __)( ___)
     )    (  /(__)\  )(__  )(__  /(__)\( (__  )__)
    (__/\__)(__)(__)(____)(____)(__)(__)\___)(____)

             a platform for experimental evolution.

"""


def main():
    """A command line interface for Wallace."""
    p = optparse.OptionParser()
    p.add_option("--deploy", "-d", action="callback", callback=deploy)
    p.add_option("--check", "-c", action="callback", callback=deploy)

    options, arguments = p.parse_args()


def deploy(*args):
    """Deploy app to psiTurk."""

    # Generate a unique id for this experiment.
    id = str(uuid.uuid4())
    print "❯ Running experiment " + id

    # Copy custom.py into this package.
    custom_py_src = os.path.join(
        os.path.dirname(os.path.realpath(__file__)),
        "custom.py")
    custom_py_dst = os.path.join(os.getcwd(), "custom.py")
    shutil.copy(custom_py_src, custom_py_dst)

    # Run psiTurk
    # with open(os.path.join(os.getcwd(), "psiturk.txt"), "w") as f:
    #     f.write("server on")

    # pexpect.run("psiturk --script psiturk.txt")
    # # pt = pexpect.spawn('psiturk')
    # # pt.logfile = file("server.log", "a")
    # # pt.expect_exact("]$")
    # # pt.sendline("server on")
    # # pt.expect_exact("on")

    # Send launch signal to server.
    config = PsiturkConfig()
    config.load_config()
    host = config.get('Server Parameters', 'host')
    port = config.get('Server Parameters', 'port')
    url = "http://" + host + ":" + port + "/launch"
    # print pexpect.run("curl -X POST " + url)


def check(*args):
    """Check that directory is a Wallace-compatible app."""
    raise NotImplementedError

if __name__ == "__main__":
    main()
