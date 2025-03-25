from __future__ import absolute_import

import logging
import multiprocessing
import os

from gunicorn import util
from gunicorn.app.base import Application
from werkzeug.middleware.proxy_fix import ProxyFix

from dallinger.config import get_config
from dallinger.utils import attach_json_logger

logger = logging.getLogger(__name__)

WORKER_CLASS = "gevent"


def when_ready(arbiter):
    # Signal to parent process that server has started
    logger.warning("Ready.")


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
        workers = config.get("threads")
        if workers == "auto":
            multiplier = config.get("worker_multiplier")
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
        }


def launch():
    config = get_config()
    config.load()
    LOG_LEVELS = [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    ]
    LOG_LEVEL = LOG_LEVELS[config.get("loglevel")]
    logging.basicConfig(format="%(asctime)s %(message)s", level=LOG_LEVEL)
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
