import gevent.monkey  # noqa: E402

gevent.monkey.patch_all()
# ^ patch must happen at top of file before other imports
import atexit  # noqa: E402
import codecs  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402

import psutil  # noqa: E402
import werkzeug  # noqa: E402

from dallinger.experiment_server import sockets  # noqa: E402
from dallinger.experiment_server.experiment_server import app  # noqa: E402, F401

# Raises for invalid game types, so the server doesn't start.
sockets.process_games()


@atexit.register
def _shutdown_logging_before_teardown():
    # Handlers that are garbage-collected during interpreter teardown take a
    # lock that calls gevent's thread functions, which teardown has already
    # cleared, and print a TypeError traceback. Logging skips that lock when
    # its handler list is empty, so flush the handlers now and forget them.
    logging.shutdown()
    logging._handlerList.clear()


os.environ["FLASK_SECRET_KEY"] = codecs.encode(os.urandom(16), "hex").decode("ascii")

if werkzeug.serving.is_running_from_reloader():
    worker = subprocess.Popen(["dallinger_heroku_worker"])
    clock = subprocess.Popen(["dallinger_heroku_clock"])

    def cleanup():
        # A killed worker can't stop its real-time runner.
        try:
            for child in psutil.Process(worker.pid).children(recursive=True):
                child.kill()
        except psutil.NoSuchProcess:
            pass
        worker.kill()
        clock.kill()

    atexit.register(cleanup)
