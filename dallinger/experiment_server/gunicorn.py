from __future__ import absolute_import

from gunicorn.app.base import Application
from gunicorn import util
import multiprocessing
from dallinger.config import get_config
import logging

logger = logging.getLogger(__file__)

app = util.import_app("dallinger.experiment_server.experiment_server:app")


def when_ready(arbiter):
    # Signal to parent process that server has started
    logger.warn('Ready.')


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
        return app

    def load_user_config(self):
        config = get_config()
        workers = config.get("threads")
        if workers == "auto":
            workers = str(multiprocessing.cpu_count() * 2 + 1)

        host = config.get("host")
        port = config.get("port")
        bind_address = "{}:{}".format(host, port)
        self.options = {
            'bind': bind_address,
            'workers': workers,
            'loglevels': self.loglevels,
            'loglevel': self.loglevels[config.get("loglevel")],
            'accesslog': config.get("logfile"),
            'errorlog': config.get("logfile"),
            'proc_name': 'dallinger_experiment_server',
            'limit_request_line': '0',
            'when_ready': when_ready,
        }


def launch():
    config = get_config()
    LOG_LEVELS = [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL
    ]
    LOG_LEVEL = LOG_LEVELS[config.get('loglevel')]
    logging.basicConfig(format='%(asctime)s %(message)s', level=LOG_LEVEL)

    # Avoid duplicate logging to stderr
    if config.get('logfile') == '-':
        logging.getLogger('gunicorn.error').propagate = False
        logging.getLogger('gunicorn.access').propagate = False

    StandaloneServer().run()


if __name__ == "__main__":
    launch()
