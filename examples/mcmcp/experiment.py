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


class Bartlett1932(Experiment):

    """Define the structure of the experiment."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in wallace).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(Bartlett1932, self).__init__(session)
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
            super(Bartlett1932, self).setup()
            for net in self.networks():
                WarOfTheGhostsSource(network=net)

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


class WarOfTheGhostsSource(Source):

    """A Source that reads in a random story from a file and transmits it."""

    __mapper_args__ = {"polymorphic_identity": "war_of_the_ghosts_source"}

    def _contents(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information() -> _contents().
        """
        stories = [
            "ghosts.md",
            "cricket.md",
            "moochi.md",
            "outwit.md",
            "raid.md",
            "species.md",
            "tennis.md",
            "vagabond.md"
        ]
        story = random.choice(stories)
        with open("static/stimuli/{}".format(story), "r") as f:
            return f.read()


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
