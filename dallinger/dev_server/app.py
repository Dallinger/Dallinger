import codecs
import os
import gevent.monkey

gevent.monkey.patch_all()  # Patch before importing app and all its dependencies

from dallinger.experiment_server.experiment_server import app  # noqa: E402, F401


os.environ["FLASK_SECRET_KEY"] = codecs.encode(os.urandom(16), "hex").decode("ascii")
