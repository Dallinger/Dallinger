"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from wallace.networks import Chain
from wallace.nodes import Source
from wallace.experiments import Experiment
from wallace import db
import random
from flask import Blueprint, Response, request
from rq import Queue
from wallace.heroku.worker import conn
import json
import random


class MCMCP(Experiment):

    """Define the structure of the experiment."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in wallace).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(MCMCP, self).__init__(session)
        self.experiment_repeats = 1
        self.network = lambda: Chain(max_size=3)
        self.setup()

    def setup(self):
        """Setup the networks.

        Setup only does stuff if there are no networks, this is so it only
        runs once at the start of the experiment. It first calls the same
        function in the super (see experiments.py in wallace). Then it adds a
        source to each network.
        """
        if not self.networks():
            super(MCMCP, self).setup()
            for net in self.networks():
                VectorSource(network=net)

    def add_node_to_network(self, node, network):
        """When a node is created it is added to the chain (see Chain in networks.py)
        and it receives any transmissions."""
        network.add_node(node)
        node.receive()

    def recruit(self):
        """Recruit one participant at a time until all networks are full."""
        if self.networks(full=False):
            self.recruiter().recruit_participants(n=1)
        else:
            self.recruiter().close_recruitment()


class VectorSource(Source):
    """A Source that transmits a random vector."""

    __mapper_args__ = {
        "polymorphic_identity": "random_vector_source"
    }

    def _contents(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information() -> _contents().
        """
        return json.dumps([random.random() for i in range(10)])


extra_routes = Blueprint(
    'extra_routes',
    __name__,
    template_folder='templates',
    static_folder='static')


@db.scoped_session_decorator
def worker_function(vector):
    """Return the given vector."""
    img = vector
    return img


@extra_routes.route("/image", methods=["POST"])
def image_post():
    """Create an image."""
    q = Queue(connection=conn)

    job = q.enqueue(
        worker_function,
        request.values['vector'])

    return Response(
        json.dumps({"job_id": job.id}),
        status=200,
        mimetype='application/json')


@extra_routes.route("/image", methods=["GET"])
def image_get():
    """Get an image."""
    q = Queue(connection=conn)

    job = q.fetch_job(request.values['job_id'])

    return Response(
        json.dumps({"image": job.result}),
        status=200,
        mimetype='application/json')
