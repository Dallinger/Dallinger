"""Monte Carlo Markov Chains with people."""

from wallace.models import Info, Transformation
from wallace.networks import Chain
from wallace.nodes import Source, Agent
from wallace.experiments import Experiment
from wallace import db
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
        self.network = lambda: Chain(max_size=100)
        self.setup()
        self.agent = MCMCPAgent

    def setup(self):
        """Setup the networks."""
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


class MCMCPAgent(Agent):

    __mapper_args__ = {
        "polymorphic_identity": "MCMCP_agent"
    }

    def update(self, infos):
        info = infos[0]
        self.replicate(info)

        # TODO: find a more logical place for this code.
        perturbed = AnimalSource.perturb(info.contents, 0.1)
        new_info = ChoosableInfo(origin=self, contents=perturbed)
        Perturbation(info_in=info, info_out=new_info)

    def _what(self):
        infos = self.infos()
        return [i for i in infos if i.chosen][0]


class AnimalSource(Source):

    """A source that transmits animal shapes."""

    __mapper_args__ = {
        "polymorphic_identity": "animal_source"
    }

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

    @staticmethod
    def perturb(contents, fractional_sd):
        """Perturb the given animal."""
        animal = json.loads(contents)

        for prop, prop_range in AnimalSource.properties.iteritems():
            range = prop_range[1] - prop_range[0]
            jittered = animal[prop] + random.gauss(0, fractional_sd * range)
            animal[prop] = max(min(jittered, prop_range[1]), prop_range[0])

        return json.dumps(animal)

    def _contents(self):

        data = {}
        for prop, prop_range in AnimalSource.properties.iteritems():
            data[prop] = random.uniform(prop_range[0], prop_range[1])

        return json.dumps(data)

    def create_information(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information().
        """
        return ChoosableInfo(origin=self, contents=self._contents())


class ChoosableInfo(Info):
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
