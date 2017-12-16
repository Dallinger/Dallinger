"""Coordination chatroom game."""

import json
import random
import time

from sqlalchemy import String
from sqlalchemy.sql.expression import cast

import dallinger as dlgr
from dallinger.models import Node, Network
from dallinger.networks import Empty
from dallinger.networks import FullyConnected
from dallinger.nodes import Source


class CoordinationChatroom(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        super(CoordinationChatroom, self).__init__(session)
        import models
        self.models = models
        
        self.experiment_repeats = 1
        self.num_participants = 4 #55 #55 #140 below
        self.initial_recruitment_size = self.num_participants #self.num_participants * 2 #note: can't do *2.5 here, won't run even if the end result is an integer
        self.quorum = self.num_participants
        #self.setup()
        if session:
            self.setup()
        self.num_mafia = 2
        self.mafia = random.sample(range(self.num_participants), self.num_mafia)
        # self.networks()[0].setup_nighttime()
        self.round_duration = 120

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
        #return Empty(max_size=self.num_participants + 1)  # add a Source
        print('HELLO')
        return FullyConnected(max_size=self.num_participants + 1)  # add a Source
        #return self.models.MafiaNetwork(max_size=self.num_participants + 1)  # add a Source


    def bonus(self, participant):
        """Give the participant a bonus for waiting."""

        DOLLARS_PER_HOUR = 5.0
        t = participant.end_time - participant.creation_time

        # keep to two decimal points otherwise doesn't work
        return round((t.total_seconds() / 3600) * DOLLARS_PER_HOUR, 2)

    def add_node_to_network(self, node, network):
        """Add node to the chain and receive transmissions."""
        network.add_node(node)
        source = network.nodes(type=Source)[0]  # find the source in the network
        source.connect(direction="to", whom=node)  # link up the source to the new node
        source.transmit(to_whom=node)  # in networks.py code, transmit info to the new node
        node.receive()  # new node receives everything

        all_edges = []

        # here are all the edges that need to be connected
        # BABY_NETWORK:
        #all_edges = [(0, 1), (0, 2), (0, 3), (2, 3)]
        #all_edges = [(0,1), (0,2)]

        # walk through edges
        for edge in all_edges:
            try:
                node0 = Node.query.filter_by(participant_id=edge[0]+1).one()
                node1 = Node.query.filter_by(participant_id=edge[1]+1).one()
                node0.connect(direction="from", whom=node1)  # connect backward
                node1.connect(direction="from", whom=node0)  # connect forward

            except Exception:
                pass

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""

        # Figure out if it's night or daytime based on current clocktime
        # elapsed_time = time.time() - self.start_time
        # # round_duration = 120
        #
        # # Get the current status of the network (night vs. day) by querying
        # # for the network and then checking its .daytime property.
        # net = Network.query.filter_by(network_id=node.network_id)
        # daytime = net.daytime
        #
        # # If it's night but should be day, then call setup_daytime()
        # if (not net.daytime and (elapsed_time / self.round_duration) % 2 == 1):
        #     # setup_daytime()
        #     net.setup_daytime()
        #
        # # If it's day but should be night, then call setup_nighttime()
        # if (net.daytime and (elapsed_time / self.round_duration) % 2 == 0):
        # # if (net.daytime):
        #     # setup_nighttime()
        #     net.setup_nighttime()

        # Proceed with normal info post request
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)


    def create_node(self, participant, network):
        """Create a node for a participant."""
        # Check how many mafia members there are.
        # num_mafioso = Nodes.query.filter....count()
        # num_mafioso = Node.query.filter_by(__mapper_args__['polymorphic_identity']="mafioso").count()
        # num_mafioso = Node.query.filter_by(type="mafioso").count()
        node_num = Node.query.filter_by().count()
        # If there aren't enough, create another:
        # SAMEE is participant an integer? is it sequential?
        # if num_mafioso < 2:
        if node_num + 1 == self.quorum:
            self.start_time = time.time()
        if node_num in self.mafia:
            return self.models.Mafioso(network=network, participant=participant)
        else:
            return self.models.Bystander(network=network, participant=participant)
        #return dlgr.nodes.Agent(network=network, participant=participant)



class FreeRecallListSource(Source):
    """A Source that reads in a random list from a file and transmits it."""

    __mapper_args__ = {
        "polymorphic_identity": "free_recall_list_source"
    }

    def _contents(self):
        """Define the contents of new Infos.
        transmit() -> _what() -> create_information() -> _contents().
        """

        #CODE FOR INDIVIDUAL EXPTS
        #(samples 60 words from the big wordlist for each participant) 
        # wordlist = "groupwordlist.md"
        # with open("static/stimuli/{}".format(wordlist), "r") as f:
        #    wordlist = f.read().splitlines()
        #    return json.dumps(random.sample(wordlist,60))



        # CODE FOR GROUP EXPTS
        # (has one word list for the experiment 
        # (draw 60 words from "groupwordlist.md") then
        # reshuffles the words within each participant

        ### read in UUID
        exptfilename = "experiment_id.txt"
        exptfile = open(exptfilename, "r") 
        UUID = exptfile.read() # get UUID of the experiment

        wordlist = "groupwordlist.md"
        with open("static/stimuli/{}".format(wordlist), "r") as f:

        	### get a wordlist for the expt
        	# reads in the file with a big list of words
        	wordlist = f.read().splitlines() 
        	# use the UUID (unique to each expt) as a seed for 
        	# the pseudorandom number generator.
        	# the random sample will be the same for everyone within an 
        	# experiment but different across experiments b/c 
        	# they have different UUIDs.
        	random.seed(UUID) 
        	# sample 60 words from large word list without replacement
        	expt_wordlist = random.sample(wordlist,1)

        	### shuffle wordlist for each participant
        	random.seed() # an actually random seed
        	random.shuffle(expt_wordlist)
        	return json.dumps(expt_wordlist)


        	

        # OLD: 
        # shuffles all words
        #wordlist = "60words.md" 
        #with open("static/stimuli/{}".format(wordlist), "r") as f:
        #    wordlist = f.read().splitlines()
        #    return json.dumps(random.sample(wordlist,60))
        ##    random.shuffle(wordlist)
        ##    return json.dumps(wordlist)
