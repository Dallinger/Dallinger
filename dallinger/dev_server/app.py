import gevent.monkey

gevent.monkey.patch_all()  # Patch before importing app and all its dependencies

import codecs  # noqa: E402
import os  # noqa: E402
from dallinger.experiment_server.experiment_server import app  # noqa: E402, F401


os.environ["FLASK_SECRET_KEY"] = codecs.encode(os.urandom(16), "hex").decode("ascii")
