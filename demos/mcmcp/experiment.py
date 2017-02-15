"""Monte Carlo Markov Chains with people."""

from dallinger.networks import Chain
from dallinger.experiments import Experiment
from dallinger import db
import random
from flask import Blueprint, Response
from operator import attrgetter


class MCMCP(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in dallinger).

        The sources module is imported here because it must be imported at
        runtime.

        A few properties are then overwritten.

        Finally, setup() is called.
        """
        super(MCMCP, self).__init__(session)
        import sources
        self.sources = sources
        self.experiment_repeats = 1
        self.trials_per_participant = 10
        self.setup()

    def create_node(self, network, participant):
        """Create a node for a participant."""
        from sources import MCMCPAgent
        return MCMCPAgent(network=network, participant=participant)

    def setup(self):
        """Setup the networks."""
        if not self.networks():
            super(MCMCP, self).setup()
            for net in self.networks():
                self.sources.AnimalSource(network=net)

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


extra_routes = Blueprint(
    'extra_routes',
    __name__,
    template_folder='templates',
    static_folder='static')


@extra_routes.route("/choice/<int:node_id>/<int:choice>", methods=["POST"])
def choice(node_id, choice):
    from sources import Agent
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
