import gevent.monkey  # noqa: E402

gevent.monkey.patch_all()
# ^ patch must happen at top of file before other imports
import atexit  # noqa: E402
import codecs  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402

import werkzeug  # noqa: E402
import werkzeug.serving  # noqa: E402

from dallinger import dev_logging  # noqa: E402

try:
    from dallinger.experiment_server.experiment_server import app  # noqa: E402, F401

    load_error = None
except Exception as error:
    # After a code change, keep serving (and watching for the fix) instead of
    # letting Flask print the traceback again for every request.
    if not werkzeug.serving.is_running_from_reloader():
        raise
    app, load_error = dev_logging.load_error_app(error), error

# Werkzeug (2.1+) colours its log lines without checking where they go: stderr.
werkzeug.serving._log_add_style = (
    getattr(werkzeug.serving, "_log_add_style", True)
    and sys.stderr.isatty()
    and "NO_COLOR" not in os.environ
)
dev_logging.setup_dev_server(app)
if load_error is not None:
    dev_logging.report_load_error(load_error)


@atexit.register
def _shutdown_logging_before_teardown():
    # Handlers that are garbage-collected during interpreter teardown take a
    # lock that calls gevent's thread functions, which teardown has already
    # cleared, and print a TypeError traceback. Logging skips that lock when
    # its handler list is empty, so flush the handlers now and forget them.
    logging.shutdown()
    # A CPython internal; skip if a future Python removes it.
    handler_list = getattr(logging, "_handlerList", None)
    if handler_list is not None:
        handler_list.clear()


os.environ["FLASK_SECRET_KEY"] = codecs.encode(os.urandom(16), "hex").decode("ascii")

if werkzeug.serving.is_running_from_reloader() and load_error is None:
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    env.pop(dev_logging.PIN_ENV, None)
    worker = subprocess.Popen(
        ["dallinger_heroku_worker"], env={**env, dev_logging.ROLE_ENV: "worker"}
    )
    clock = subprocess.Popen(
        ["dallinger_heroku_clock"], env={**env, dev_logging.ROLE_ENV: "clock"}
    )

    def cleanup():
        worker.kill()
        clock.kill()

    atexit.register(cleanup)
