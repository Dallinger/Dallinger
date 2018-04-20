"""Mafia game."""

import json
import random

import dallinger as dlgr
from dallinger import db
from dallinger.models import Node, Network, timenow
from dallinger.nodes import Source
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
        self.num_participants = 4
        self.initial_recruitment_size = self.num_participants # * 2 # Note: can't do *2.5 here, won't run even if the end result is an integer
        self.quorum = self.num_participants
        if session:
            self.setup()
        self.num_mafia = 1
        self.known_classes["Text"] = models.Text
        self.known_classes["Vote"] = models.Vote

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
        source.transmit(to_whom=node)  # in networks.py code, transmit info to the new node
        node.receive()  # new node receives everything

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""

        # Proceed with normal info post request
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)

    def create_node(self, participant, network):
        """Create a node for a participant."""
        # Check how many mafia members there are.
        # If there aren't enough, create another:
        num_mafioso = Node.query.filter_by(type="mafioso").count()
        if num_mafioso < self.num_mafia:
            mafioso = self.models.Mafioso(network=network, participant=participant)
            mafioso.fake_name = str(fake.name())
            mafioso.alive = 'True'
            return mafioso
        else:
            bystander = self.models.Bystander(network=network, participant=participant)
            bystander.fake_name = str(fake.name())
            bystander.alive = 'True'
            return bystander


extra_routes = Blueprint(
    'extra_routes',
    __name__,
    template_folder='templates',
    static_folder='static')


@extra_routes.route("/phase/<int:node_id>/<int:switches>/<string:was_daytime>", methods=["GET"])
def phase(node_id, switches, was_daytime):
    try:
        exp = MafiaExperiment(db.session)
        this_node = Node.query.filter_by(id=node_id).one()
        net = Network.query.filter_by(id=this_node.network_id).one()
        nodes = Node.query.filter_by(network_id=net.id).order_by('creation_time').all()
        node = nodes[-1]
        elapsed_time = timenow() - node.creation_time
        daytime = (net.daytime == 'True')
        day_round_duration = 150
        night_round_duration = 30
        break_duration = 3
        daybreak_duration = day_round_duration + break_duration
        nightbreak_duration = night_round_duration + break_duration
        time = elapsed_time.total_seconds()
        if switches % 2 == 0:
            time = night_round_duration - (elapsed_time.total_seconds() - switches / 2 * daybreak_duration) % night_round_duration
        else:
            time = day_round_duration - (elapsed_time.total_seconds() - (switches + 1) / 2 * nightbreak_duration) % day_round_duration
        time = int(time)
        victim_name = None
        victim_type = None
        winner = None

        # If it's night but should be day, then call setup_daytime()
        if not daytime and (int(elapsed_time.total_seconds() - switches / 2 * daybreak_duration) == night_round_duration):
            victim_name, winner = net.setup_daytime()
        # If it's day but should be night, then call setup_nighttime()
        elif daytime and (int(elapsed_time.total_seconds() - (switches + 1) / 2 * nightbreak_duration) == day_round_duration):
            victim_name, winner = net.setup_nighttime()
            victim_type = Node.query.filter_by(property1=victim_name).one().type
        elif was_daytime != net.daytime:
            nodes = Node.query.filter_by(network_id=net.id, property2='True').all()
            mafiosi = Node.query.filter_by(network_id=net.id, property2='True', type='mafioso').all()
            victim_name = Node.query.filter_by(network_id=net.id, property2='False').order_by('property3').all()[-1].property1
            if daytime:
                if len(mafiosi) > len(nodes) - len(mafiosi) - 1:
                    winner = 'mafia'
            else:
                victim_type = Node.query.filter_by(property1=victim_name).one().type
                if len(mafiosi) >= len(nodes) - len(mafiosi) - 1:
                    winner = 'mafia'
            if len(mafiosi) == 0:
                winner = 'townspeople'
        if winner is not None:
            victim_type = Node.query.filter_by(property1=victim_name).one().type

        exp.save()

        return Response(
            response=json.dumps({
                'time': time, 'daytime': net.daytime,
                'victim': [victim_name, victim_type], 'winner': winner
            }),
            status=200,
            mimetype='application/json')
    except Exception:
        db.logger.exception('Error fetching phase')
        return Response(
            status=403,
            mimetype='application/json')


@extra_routes.route("/live_participants/<int:node_id>/<int:get_all>", methods=["GET"])
def live_participants(node_id, get_all):
    try:
        exp = MafiaExperiment(db.session)
        this_node = Node.query.filter_by(id=node_id).one()
        if get_all == 1:
            nodes = Node.query.filter_by(network_id=this_node.network_id, property2='True').all()
        else:
            nodes = Node.query.filter_by(network_id=this_node.network_id, property2='True', type='mafioso').all()
        participants = []
        for node in nodes:
            if node.property1 == this_node.property1:
                participants.append(node.property1 + ' (you!)')
            else:
                participants.append(node.property1)
        random.shuffle(participants)

        exp.save()

        return Response(
            response=json.dumps({'participants': participants}),
            status=200,
            mimetype='application/json')
    except Exception:
        db.logger.exception('Error fetching live participants')
        return Response(
            status=403,
            mimetype='application/json')

class FreeRecallListSource(Source):
    """A Source that reads in a random list from a file and transmits it."""

    __mapper_args__ = {
        "polymorphic_identity": "free_recall_list_source"
    }

    def _contents(self):
        """Define the contents of new Infos.
        transmit() -> _what() -> create_information() -> _contents().
        """

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
