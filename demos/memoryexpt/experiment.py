"""Coordination chatroom game."""

import dallinger as dlgr
from dallinger.nodes import Source
import random
import json

class CoordinationChatroom(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        super(CoordinationChatroom, self).__init__(session)
        self.experiment_repeats = 1
        self.num_participants = dlgr.config.experiment_configuration.n
        self.initial_recruitment_size = self.num_participants
        self.quorum = self.num_participants
        self.setup()

    def setup(self):
        """Setup the networks.

        Setup only does stuff if there are no networks, this is so it only
        runs once at the start of the experiment. It first calls the same
        function in the super (see experiments.py in dallinger). Then it adds a
        source to each network.
        """
        if not self.networks():
            super(CoordinationChatroom, self).setup()
            for net in self.networks():
                FreeRecallListSource(network=net)

    def create_network(self):
        """Create a new network by reading the configuration file."""
        class_ = getattr(
            dlgr.networks,
            dlgr.config.experiment_configuration.network
        )
        return class_(max_size=self.num_participants+1) # add a Source

    def add_node_to_network(self, node, network):
        """Add node to the chain and receive transmissions."""
        network.add_node(node)
        source = network.nodes(type=Source)[0] #find the source in the network
        source.connect(direction="to",whom=node) # link up the source to the new node
        source.transmit(to_whom=node) # in networks.py code, transmit info to the new node
        node.receive() # new node receives everything

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return dlgr.nodes.Agent(network=network, participant=participant)

class FreeRecallListSource(Source):
    """A Source that reads in a random list from a file and transmits it."""

    __mapper_args__ = {
        "polymorphic_identity": "free_recall_list_source"
    }

    def _contents(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information() -> _contents().
        """

        wordlist = "40words.md" #random.choice(wordlists)
        with open("static/stimuli/{}".format(wordlist), "r") as f:
            wordlist =  f.read().splitlines()
            return json.dumps(random.sample(wordlist,5))
