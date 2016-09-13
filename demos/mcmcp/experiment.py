"""Monte Carlo Markov Chains with people."""

from dallinger.models import Info, Transformation
from dallinger.networks import Chain
from dallinger.nodes import Source, Agent
from dallinger.experiments import Experiment
from dallinger import db
import random
from flask import Blueprint, Response
import json
from sqlalchemy import Boolean
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import cast
from operator import attrgetter


class MCMCP(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        super(MCMCP, self).__init__(session)
        self.experiment_repeats = 1
        self.trials_per_participant = 10
        self.setup()

    def create_node(self, network, participant):
        """Create a node for a participant."""
        return MCMCPAgent(network=network, participant=participant)

    def setup(self):
        """Setup the networks."""
        if not self.networks():
            super(MCMCP, self).setup()
            for net in self.networks():
                AnimalSource(network=net)

    def create_network(self):
        """Create a new network."""
        return Chain(max_size=100)

    def get_network_for_participant(self, participant):
        if len(participant.nodes(failed="all")) < self.trials_per_participant:
            return random.choice(self.networks())
        else:
            return None

    def add_node_to_network(self, node, network):
        """When a node is created it is added to the chain (see Chain in networks.py)
        and it receives any transmissions."""
        network.add_node(node)
        parent = node.neighbors(direction="from")[0]
        parent.transmit()
        node.receive()


class MCMCPAgent(Agent):

    __mapper_args__ = {
        "polymorphic_identity": "MCMCP_agent"
    }

    def update(self, infos):
        info = infos[0]
        self.replicate(info)
        new_info = AnimalInfo(origin=self, contents=info.perturbed_contents())
        Perturbation(info_in=info, info_out=new_info)

    def _what(self):
        infos = self.infos()
        return [i for i in infos if i.chosen][0]


class AnimalSource(Source):
    """A source that transmits animal shapes."""

    __mapper_args__ = {
        "polymorphic_identity": "animal_source"
    }

    def create_information(self):
        """Create a new Info.

        transmit() -> _what() -> create_information().
        """
        return AnimalInfo(origin=self, contents=None)


class AnimalInfo(Info):
    """An Info that can be chosen."""

    __mapper_args__ = {
        "polymorphic_identity": "vector_info"
    }

    @hybrid_property
    def chosen(self):
        """Use property1 to store whether an info was chosen."""
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

    properties = {
        "foot_spread": [0, 1],
        "body_height": [0.1, 1.5],
        "body_tilt": [-15, 45],
        "tail_length": [0.05, 1.2],
        "tail_angle": [-45, 190],
        "neck_length": [0, 2.5],
        "neck_angle": [90, 180],
        "head_length": [0.05, 0.75],
        "head_angle": [5, 80]
    }

    def __init__(self, origin, contents=None):
        # check the origin hasn't failed
        if origin.failed:
            raise ValueError("{} cannot create an info as it has failed".format(origin))

        self.origin = origin
        self.origin_id = origin.id
        self.network_id = origin.network_id
        self.network = origin.network

        if contents is not None:
            self.contents = contents
        else:
            data = {}
            for prop, prop_range in self.properties.iteritems():
                data[prop] = random.uniform(prop_range[0], prop_range[1])
            self.contents = json.dumps(data)

    def perturbed_contents(self):
        """Perturb the given animal."""
        animal = json.loads(self.contents)

        for prop, prop_range in self.properties.iteritems():
            range = prop_range[1] - prop_range[0]
            jittered = animal[prop] + random.gauss(0, 0.1 * range)
            animal[prop] = max(min(jittered, prop_range[1]), prop_range[0])

        return json.dumps(animal)


class Perturbation(Transformation):
    """A perturbation is a transformation that perturbs the contents."""

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
