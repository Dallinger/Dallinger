"""Mafia game."""

import json
import random
import time

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Boolean
from sqlalchemy.sql.expression import cast

import dallinger as dlgr
from dallinger import db
from dallinger.models import Node, Network, timenow
# from dallinger.networks import Empty
# from dallinger.networks import FullyConnected
# from dallinger.networks import MafiaNetwork
from dallinger.nodes import Source
# from dallinger.command_line import log
from flask import Blueprint, Response
from faker import Faker
fake = Faker()


class MafiaExperiment(dlgr.experiments.Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session):
        """Initialize the experiment."""
        super(MafiaExperiment, self).__init__(session)
        import models
        self.models = models

        self.experiment_repeats = 1
        self.num_participants = 3 #2 #55 #55 #140 below
        self.initial_recruitment_size = self.num_participants # * 2 # Note: can't do *2.5 here, won't run even if the end result is an integer
        self.quorum = self.num_participants
        if session:
            self.setup()
        self.num_mafia = 1
        # self.mafia = random.sample(range(self.num_participants), self.num_mafia)
        # self.round_duration = 120
        self.round_duration = 0
        # self.start_time = timenow()
        # print(self.start_time)
        # self.start_time = time.time()

    def setup(self):
        """Setup the networks.

        Setup only does stuff if there are no networks, this is so it only
        runs once at the start of the experiment. It first calls the same
        function in the super (see experiments.py in dallinger). Then it adds a
        source to each network.
        """
        if not self.networks():
            super(MafiaExperiment, self).setup()
            for net in self.networks():
                FreeRecallListSource(network=net)

    def create_network(self):
        """Create a new network by reading the configuration file."""

        mafia_network = self.models.MafiaNetwork(max_size=self.num_participants + 1)  # add a Source
        mafia_network.daytime = 'False'
        return mafia_network


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
        # source.connect(direction="both", whom=node)  # link up the source to the new node
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

        # # Figure out if it's night or daytime based on current clocktime
        # # elapsed_time = self.start_time
        # # elapsed_time = time.time() - self.start_time
        # # elapsed_time = timenow() - self.start_time
        # elapsed_time = timenow() - Node.query.order_by('creation_time').first().creation_time
        # # elapsed_time = timenow() - Participant.query.filter().order_by('creation_time').last() # creation time of participant
        # # log("elapsed_time")
        # # self.round_duration = elapsed_time - self.round_duration
        #
        # # Get the current status of the network (night vs. day) by querying
        # # for the network and then checking its .daytime property.
        # net = Network.query.filter_by(id=node.network_id).one()
        # # net = node.network
        # daytime = net.daytime
        #
        # # If it's night but should be day, then call setup_daytime()
        # if (not daytime) and ((elapsed_time.total_seconds() // self.round_duration) % 2 == 1):
        # # if (not daytime) and (elapsed_time.total_seconds() >= self.round_duration):
        #     net.setup_daytime()
        #
        # # # If it's day but should be night, then call setup_nighttime()
        # if daytime and ((elapsed_time.total_seconds() // self.round_duration) % 2 == 0):
        # # if (daytime):
        #     net.setup_nighttime()
        #
        # # if not daytime:
        # #     net.setup_daytime()
        #
        # # if not votetime:
        # #     net.setup_votetime()
        # #
        # # if net.daytime:
        # #     net.setup_nighttime()
        #
        # # Proceed with normal info post request
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)


    def create_node(self, participant, network):
        """Create a node for a participant."""
        # Check how many mafia members there are.
        # num_mafioso = Nodes.query.filter....count()
        # num_mafioso = Node.query.filter_by(__mapper_args__['polymorphic_identity']="mafioso").count()
        # If there aren't enough, create another:
        # SAMEE is participant an integer? is it sequential?
        # if Node.query.filter_by().count() == self.quorum:
        # self.start_time = time.time()
        # self.start_time = timenow()
        num_mafioso = Node.query.filter_by(type="mafioso").count()
        if num_mafioso < self.num_mafia:
        # # num_nodes = Node.query.count() - 1
        # if num_mafioso < self.num_mafia and random.random() < self.num_mafia / self.num_participants:
        # # node_num = Node.query.count() - 1
        # # if node_num in self.mafia:
            mafioso = self.models.Mafioso(network=network, participant=participant)
            mafioso.fake_name = str(fake.name())
            mafioso.alive = 'True'
            return mafioso
        # elif self.num_participants - num_nodes == self.num_mafia - num_mafioso:
        #     return self.models.Mafioso(network=network, participant=participant)
        else:
            bystander = self.models.Bystander(network=network, participant=participant)
            bystander.fake_name = str(fake.name())
            bystander.alive = 'True'
            return bystander
        #return dlgr.nodes.Agent(network=network, participant=participant)

extra_routes = Blueprint(
    'extra_routes',
    __name__,
    template_folder='templates',
    static_folder='static')


@extra_routes.route("/phase", methods=["GET"])
def phase():
    try:
        exp = MafiaExperiment(db.session)
        nodes = Node.query.order_by('creation_time').all()
        node = nodes[-1]
        elapsed_time = timenow() - node.creation_time
        net = Network.query.filter_by(id=node.network_id).one()
        daytime = (net.daytime == 'True')
        round_duration = 30
        name = elapsed_time.total_seconds()
        end = False
        winner = None

        # If it's night but should be day, then call setup_daytime()
        if not daytime and ((elapsed_time.total_seconds() // round_duration) % 2 == 1):
            name = net.setup_daytime()

        # If it's day but should be night, then call setup_nighttime()
        if daytime and ((elapsed_time.total_seconds() // round_duration) % 2 == 0):
            name, end, winner = net.setup_nighttime()

        exp.save()

        return Response(
            # response=net.daytime,
            # response=str(name),
            response=json.dumps({ "name": name, "end": end, "winner": winner }),
            status=200,
            mimetype='application/json')
    except:
        return Response(
            status=403,
            mimetype='application/json')

# @extra_routes.route("/name/<int:node_id>", methods=["GET"])
# def name(node_id):
#     try:
#         exp = MafiaExperiment(db.session)
#         node = Node.query.filter_by(id=node_id).one()
#         fake_name = node.fake_name
#
#         exp.save()
#
#         return Response(
#             response=str(fake_name),
#             status=200,
#             mimetype='application/json')
#     except:
#         return Response(
#             status=403,
#             mimetype='application/json')

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
        # return json.dumps(self.network.nodes())
        # return json.dumps(Network.query.filter_by(id=self.network_id).one().nodes())


        # OLD:
        # shuffles all words
        #wordlist = "60words.md"
        #with open("static/stimuli/{}".format(wordlist), "r") as f:
        #    wordlist = f.read().splitlines()
        #    return json.dumps(random.sample(wordlist,60))
        ##    random.shuffle(wordlist)
        ##    return json.dumps(wordlist)
