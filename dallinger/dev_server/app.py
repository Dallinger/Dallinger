import codecs
import os
import gevent.monkey

from dallinger.experiment_server.experiment_server import app


gevent.monkey.patch_all()

app.config["EXPLAIN_TEMPLATE_LOADING"] = True
os.environ["FLASK_SECRET_KEY"] = codecs.encode(os.urandom(16), "hex").decode("ascii")
