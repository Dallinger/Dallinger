"""The base experiment class."""

from wallace.models import Network, Node, Info, Transformation, Participant
from wallace.information import Gene, Meme, State
from wallace.nodes import Agent, Source, Environment
from wallace.transformations import Compression, Response
from wallace.transformations import Mutation, Replication
from sqlalchemy import and_
import random
import sys
from collections import Counter
from operator import itemgetter


class Experiment(object):
    """Define the structure of an experiment."""

    def __init__(self, session):
        """Initialize an experiment object."""
        from recruiters import PsiTurkRecruiter
        self.verbose = True
        self.task = "Experiment title"
        self.session = session
        self.practice_repeats = 0
        self.experiment_repeats = 0
        self.recruiter = PsiTurkRecruiter
        self.initial_recruitment_size = 1
        self.known_classes = {
            "Agent": Agent,
            "Compression": Compression,
            "Environment": Environment,
            "Gene": Gene,
            "Info": Info,
            "Meme": Meme,
            "Mutation": Mutation,
            "Node": Node,
            "Replication": Replication,
            "Response": Response,
            "Source": Source,
            "State": State,
            "Transformation": Transformation,
        }

    def setup(self):
        """Create the networks if they don't already exist."""
        if not self.networks():
            for _ in range(self.practice_repeats):
                network = self.create_network()
                network.role = "practice"
                self.session.add(network)
            for _ in range(self.experiment_repeats):
                network = self.create_network()
                network.role = "experiment"
                self.session.add(network)
            self.session.commit()

    def create_network(self):
        """Return a new network."""
        return self.network_type()

    def network_type(self):
        return Network

    def networks(self, role="all", full="all"):
        """All the networks in the experiment."""
        if full not in ["all", True, False]:
            raise ValueError("full must be boolean or all, it cannot be {}"
                             .format(full))

        if full == "all":
            if role == "all":
                return Network.query.all()
            else:
                return Network\
                    .query\
                    .filter_by(role=role)\
                    .all()
        else:
            if role == "all":
                return Network.query.filter_by(full=full)\
                    .all()
            else:
                return Network\
                    .query\
                    .filter(and_(Network.role == role, Network.full == full))\
                    .all()

    def get_network_for_participant(self, participant):
        """Find a network for a participant.

        If no networks are available, None will be returned.
        """
        key = participant.id
        networks_with_space = Network.query.filter_by(full=False).all()
        networks_participated_in = [
            node.network_id for node in
            Node.query.with_entities(Node.network_id)
                .filter_by(participant_id=participant.id).all()
        ]

        legal_networks = [
            net for net in networks_with_space
            if net.id not in networks_participated_in
        ]

        if not legal_networks:
            self.log("No networks available, returning None", key)
            return None

        self.log("{} networks out of {} available"
                 .format(len(legal_networks),
                         (self.practice_repeats + self.experiment_repeats)),
                 key)

        legal_practice_networks = [net for net in legal_networks
                                   if net.role == "practice"]
        if legal_practice_networks:
            chosen_network = legal_practice_networks[0]
            self.log("Practice networks available."
                     "Assigning participant to practice network {}."
                     .format(chosen_network.id), key)
        else:
            chosen_network = random.choice(legal_networks)
            self.log("No practice networks available."
                     "Assigning participant to experiment network {}"
                     .format(chosen_network.id), key)
        return chosen_network

    def make_node_for_participant(self, participant, network):
        """Create a node for a participant."""
        return self.node_type()(participant=participant, network=network)

    def node_type(self):
        return Node

    def add_node_to_network(self, node, network):
        """Add a node to a network."""
        network.add_node(node)

    def data_check(self, participant):
        """Check that the data are acceptable."""
        return True

    def bonus(self, participant):
        """The bonus to be awarded to the given participant."""
        return 0

    def bonus_reason(self):
        """The reason offered to the participant for giving the bonus."""
        return "Thank for participating! Here is your bonus."

    def attention_check(self, participant):
        """Check if participant performed adequately."""
        return True

    def submission_successful(self, participant):
        """Run when a participant submits successfully."""
        pass

    def recruit(self):
        """Recruit participants to the experiment as needed."""
        if self.networks(full=False):
            self.log("Network space available: recruiting 1 more participant",
                     "-----")
            self.recruiter().recruit_participants(n=1)
        else:
            self.log("All networks full: closing recruitment", "-----")
            self.recruiter().close_recruitment()

    def log(self, text, key="?????", force=False):
        """Print a string to the logs."""
        if force or self.verbose:
            print ">>>> {} {}".format(key, text)
            sys.stdout.flush()

    def log_summary(self):
        """Log a summary of all the participants' status codes."""
        participants = Participant.query\
            .with_entities(Participant.status).all()
        counts = Counter([p.status for p in participants])
        sorted_counts = sorted(counts.items(), key=itemgetter(0))
        self.log("Status summary: {}".format(str(sorted_counts)))
        return sorted_counts

    def save(self, *objects):
        """Add all the objects to the session and commit them."""
        if len(objects) > 0:
            self.session.add_all(objects)
        self.session.commit()

    def node_post_request(self, participant, node):
        """Run when a request to make a node is complete."""
        pass

    def node_get_request(self, node=None, nodes=None):
        """Run when a request to get nodes is complete."""
        pass

    def vector_post_request(self, node, vectors):
        """Run when a request to connect is complete."""
        pass

    def vector_get_request(self, node, vectors):
        """Run when a request to get vectors is complete."""
        pass

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""
        pass

    def info_get_request(self, node, infos):
        """Run when a request to get infos is complete."""
        pass

    def transmission_post_request(self, node, transmissions):
        """Run when a request to transmit is complete."""
        pass

    def transmission_get_request(self, node, transmissions):
        """Run when a request to get transmissions is complete."""
        pass

    def transformation_post_request(self, node, transformation):
        """Run when a request to transform an info is complete."""
        pass

    def transformation_get_request(self, node, transformations):
        """Run when a request to get transformations is complete."""
        pass

    def fail_participant(self, participant):
        """Fail all the nodes of a participant."""
        participant_nodes = Node.query\
            .filter_by(participant_id=participant.id, failed=False)\
            .all()

        for node in participant_nodes:
            node.fail()

    def data_check_failed(self, participant):
        """What to do if a participant fails the data check."""
        self.fail_participant(participant)

    def attention_check_failed(self, participant):
        """What to do if a participant fails the attention check."""
        self.fail_participant(participant)

    def assignment_abandoned(self, participant):
        """What to do if a participant abandons the hit."""
        self.fail_participant(participant)

    def assignment_returned(self, participant):
        """What to do if a participant returns the hit."""
        self.fail_participant(participant)
