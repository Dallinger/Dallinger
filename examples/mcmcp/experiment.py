"""Monte Carlo Markov Chains with people."""

from wallace.models import Info, Transformation
from wallace.networks import Chain
from wallace.nodes import Source, Agent
from wallace.experiments import Experiment
from wallace import db
import random
from flask import Blueprint, Response, request
from rq import Queue
from wallace.heroku.worker import conn
import json
from sqlalchemy import Boolean
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import cast
from operator import attrgetter


class MCMCP(Experiment):

    """Define the structure of the experiment."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in wallace).

        A few properties are then overwritten.
        Finally, setup() is called.
        """
        super(MCMCP, self).__init__(session)
        self.experiment_repeats = 1
        self.trials_per_participant = 10
        self.network = lambda: Chain(max_size=100)
        self.setup()
        self.agent = MCMCPAgent

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
                AnimalSource(network=net)

    def get_network_for_participant(self, participant):
        if len(participant.nodes(failed="all")) < self.trials_per_participant:
            return random.choice(self.networks())
        else:
            return None

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


class MCMCPAgent(Agent):

    __mapper_args__ = {
        "polymorphic_identity": "MCMCP_agent"
    }

    def update(self, infos):
        info = infos[0]
        self.replicate(info)
        new_info = ChoosableInfo(origin=self, contents=self.perturb(json.loads(info.contents)))
        Perturbation(info_in=info, info_out=new_info)

    def perturb(self, l):
        return json.dumps([abs(v + random.random() - 0.5) for v in l])

    def _what(self):
        infos = self.infos()
        return [i for i in infos if i.chosen][0]


class AnimalSource(Source):
    """A source that transmits animal shapes."""

    __mapper_args__ = {
        "polymorphic_identity": "animal_source"
    }

    def _contents(self):

        data = {
            "foot_spread": random.uniform(0, 1),
            "body_height": random.uniform(0.1, 1.5),
            "body_tilt": random.uniform(-15, 45),
            "tail_length": random.uniform(0.05, 1.2),
            "tail_angle": random.uniform(-45, 190),
            "neck_length": random.uniform(0, 2.5),
            "neck_angle": random.uniform(90, 180),
            "head_length": random.uniform(0.05, 0.75),
            "head_angle": random.uniform(5, 80)
        }

        return json.dumps(data)

    def create_information(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information().
        """
        return ChoosableInfo(origin=self, contents=self._contents())


class ChoosableInfo(Info):

    __mapper_args__ = {
        "polymorphic_identity": "vector_info"
    }

    @hybrid_property
    def chosen(self):
        try:
            return bool(self.property1)
        except TypeError:
            return None

    @chosen.setter
    def chosen(self, chosen):
        """Assign chosen to property1."""
        self.property1 = repr(chosen)

    @chosen.expression
    def chosen(self):
        """Retrieve chosen via property1."""
        return cast(self.property1, Boolean)


class Perturbation(Transformation):

    __mapper_args__ = {
        "polymorphic_identity": "perturbation"
    }


extra_routes = Blueprint(
    'extra_routes',
    __name__,
    template_folder='templates',
    static_folder='static')


@extra_routes.route("/choice/<int:node_id>/<int:choice>", methods=["POST"])
def choice(node_id, choice):
    try:
        exp = MCMCP(db.session)
        node = Agent.query.get(node_id)
        infos = node.infos()

        if choice == 0:
            info = max(infos, key=attrgetter("id"))
        elif choice == 1:
            info = min(infos, key=attrgetter("id"))
        else:
            raise ValueError("Choice must be 1 or 0")

        info.chosen = True
        exp.save()

        return Response(
            status=200,
            mimetype='application/json')
    except:
        return Response(
            status=403,
            mimetype='application/json')


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
