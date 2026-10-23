import logging
import multiprocessing
import os
import signal

import gevent
from gunicorn import util
from gunicorn.app.base import Application
from werkzeug.middleware.proxy_fix import ProxyFix

from dallinger.config import LOG_LEVELS, get_config
from dallinger.utils import attach_json_logger, get_exp_klass

logger = logging.getLogger(__name__)

WORKER_CLASS = "gevent"
# Web processes per CPU when ``web_processes = auto``, unless the deprecated
# ``worker_multiplier`` is set.
DEFAULT_WEB_PROCESSES_PER_CPU = 1.5


def experiment_hook(func_name, *args, **kwargs):
    exp_klass = get_exp_klass()
    if exp_klass is not None:
        return getattr(exp_klass, func_name)(*args, **kwargs)
    return None


def when_ready(arbiter):
    # Signal to parent process that server has started
    logger.warning("Ready.")
    return experiment_hook("gunicorn_when_ready", arbiter)


def on_exit(server):
    return experiment_hook("gunicorn_on_exit", server)


def worker_exit(server, worker):
    return experiment_hook("gunicorn_worker_exit", server, worker)


def post_worker_init(worker):
    from dallinger.experiment_server import sockets

    # Raises for invalid game types, so the worker doesn't start.
    sockets.process_games()
    close_sockets_on_sigterm()
    return experiment_hook("gunicorn_post_worker_init", worker)


def close_sockets_on_sigterm():
    """Make SIGTERM close the worker's websockets, after running the handler
    already installed for it.

    Gunicorn's worker waits for its handlers to finish before it exits, and a
    websocket handler never finishes by itself. Heroku and Docker kill the
    process before gunicorn's wait runs out, so without this no handler would
    finish and no real-time session would get its leaves.
    """
    from dallinger.experiment_server import sockets

    previous = signal.getsignal(signal.SIGTERM)

    def handle_sigterm(signum, frame):
        if callable(previous):
            previous(signum, frame)
        # A signal handler interrupts whatever greenlet was running.
        gevent.spawn(sockets.chat_backend.close_all)

    signal.signal(signal.SIGTERM, handle_sigterm)
    # signal.signal clears this, and gunicorn sets it so that system calls
    # SIGTERM interrupts are restarted.
    signal.siginterrupt(signal.SIGTERM, False)


class StandaloneServer(Application):
    loglevels = ["debug", "info", "warning", "error", "critical"]

    def __init__(self):
        """__init__ method
        Load the base config and assign some core attributes.
        """
        self.usage = None
        self.cfg = None
        self.callable = None
        self.prog = None
        self.logger = None

        self.load_user_config()
        self.do_load_config()

    @property
    def port(self):
        """Heroku sets the port its running on as an environment variable"""
        return os.environ.get("PORT")

    def init(self, *args):
        """init method
        Takes our custom options from self.options and creates a config
        dict which specifies custom settings.
        """
        cfg = {}
        for k, v in self.options.items():
            if k.lower() in self.cfg.settings and v is not None:
                cfg[k.lower()] = v
        return cfg

    def load(self):
        """Return our application to be run."""
        app = util.import_app("dallinger.experiment_server.sockets:app")
        app.secret_key = app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY")
        if self.options.get("mode") == "debug":
            app.debug = True
        else:
            app = ProxyFix(app)
        return app

    def load_user_config(self):
        config = get_config()
        workers = config.get("web_processes")
        if workers == "auto":
            multiplier = config.get("worker_multiplier", DEFAULT_WEB_PROCESSES_PER_CPU)
            workers = str(int(round(multiprocessing.cpu_count() * multiplier)) + 1)

        host = config.get("host")
        mode = config.get("mode")
        bind_address = "{}:{}".format(host, self.port)
        self.options = {
            "bind": bind_address,
            "workers": workers,
            "worker_class": WORKER_CLASS,
            "loglevels": self.loglevels,
            "loglevel": self.loglevels[config.get("loglevel")],
            "errorlog": "-",
            "accesslog": "-",
            "mode": mode,
            "proc_name": "dallinger_experiment_server",
            "limit_request_line": "0",
            "when_ready": when_ready,
            "on_exit": on_exit,
            "worker_exit": worker_exit,
            "post_worker_init": post_worker_init,
        }


def launch():
    config = get_config(load=True)
    logging.basicConfig(
        format="%(asctime)s %(message)s", level=LOG_LEVELS[config.get("loglevel")]
    )
    # Avoid duplicate logging to stderr
    error_logger = logging.getLogger("gunicorn.error")
    error_logger.propagate = False
    access_logger = logging.getLogger("gunicorn.access")
    access_logger.propagate = False
    attach_json_logger(error_logger)
    attach_json_logger(access_logger)

    # Set up logging to file
    # (We're not using gunicorn's errorlog and accesslog settings
    # for this because it redirects stdout and stderr)
    logfile = config.get("logfile")
    if config.get("logfile") != "-":
        handler = logging.FileHandler(logfile)
        error_logger.addHandler(handler)
        access_logger.addHandler(handler)

    StandaloneServer().run()


if __name__ == "__main__":
    launch()
