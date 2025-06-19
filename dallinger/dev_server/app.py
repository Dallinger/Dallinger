import gevent.monkey  # noqa: E402

gevent.monkey.patch_all()
# ^ patch must happen at top of file before other imports
import atexit  # noqa: E402
import codecs  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

import werkzeug  # noqa: E402

from dallinger.experiment_server.experiment_server import app  # noqa: E402, F401

os.environ["FLASK_SECRET_KEY"] = codecs.encode(os.urandom(16), "hex").decode("ascii")

if werkzeug.serving.is_running_from_reloader():
    worker = subprocess.Popen(["dallinger_heroku_worker"])
    clock = subprocess.Popen(["dallinger_heroku_clock"])

    def cleanup():
        worker.kill()
        clock.kill()

    atexit.register(cleanup)
