"""The base experiment class."""

from wallace.models import Network, Node, Info, Transformation, Participant
from wallace.information import Gene, Meme, State
from wallace.nodes import Agent, Source, Environment
from wallace.transformations import Mutation, Replication, Compression, Response
from sqlalchemy import and_
import random
import inspect
import sys
from collections import Counter
from operator import itemgetter


class Experiment(object):

    def __init__(self, session):
        from recruiters import PsiTurkRecruiter
        self.verbose = True
        self.task = "Experiment title"
        self.session = session
        self.practice_repeats = 0
        self.experiment_repeats = 0
        self.recruiter = PsiTurkRecruiter
        self.initial_recruitment_size = 1
        self.known_classes = {
            "Info": Info, "Gene": Gene, "Meme": Meme, "State": State,
            "Node": Node, "Agent": Agent, "Source": Source, "Environment": Environment,
            "Transformation": Transformation, "Mutation": Mutation,
            "Replication": Replication, "Compression": Compression, "Response": Response
        }

    def setup(self):
        """Create the networks iff they don't already exist."""
        if not self.networks():
            for _ in range(self.practice_repeats):
                network = self.network()
                network.role = "practice"
                self.session.add(network)
            for _ in range(self.experiment_repeats):
                network = self.network()
                network.role = "experiment"
                self.session.add(network)
            self.save()

    def networks(self, role="all", full="all"):
        """All the networks in the experiment."""
        if full not in ["all", True, False]:
            raise ValueError("full must be boolean or all, it cannot be {}".format(full))

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

    def get_network_for_participant(self, participant_id):
        key = participant_id[0:5]
        networks_with_space = Network.query.filter_by(full=False).all()
        networks_participated_in = [
            node.network_id for node in
            Node.query.with_entities(Node.network_id).filter_by(participant_id=participant_id).all()
        ]

        legal_networks = [
            net for net in networks_with_space if net.id not in networks_participated_in
        ]

        if not legal_networks:
            self.log("No networks available, returning None", key)
            return None

        self.log("{} networks out of {} available"
                 .format(len(legal_networks),
                        (self.practice_repeats + self.experiment_repeats)),
                 key)

        legal_practice_networks = [net for net in legal_networks if net.role == "practice"]
        if legal_practice_networks:
            chosen_network = legal_practice_networks[0]
            self.log("Practice networks available. Assigning participant to practice network {}.".format(chosen_network.id), key)
        else:
            chosen_network = random.choice(legal_networks)
            self.log("No practice networks available. Assigning participant to experiment network {}".format(chosen_network.id), key)
        return chosen_network

    def make_node_for_participant(self, participant, network):
        if inspect.isclass(self.agent):
            if issubclass(self.agent, Node):
                node = self.agent(participant=participant, network=network)
            else:
                raise ValueError("{} is not a subclass of Node".format(self.agent))
        else:
            if participant.status in [1, 2]:
                node = self.agent(network=network)(participant=participant, network=network)
            else:
                self.log("Participant status = {}, node creation aborted".format(participant.status))
                return None

        self.log("Node successfully generated, recalculating if network is full")
        network.calculate_full()
        return node

    def add_node_to_network(self, participant_id, node, network):
        network.add_node(node)

    def receive_transmissions(self, transmissions):
        for t in transmissions:
            t.mark_received()

    def data_check(self, participant=None):
        """Check that the data are acceptable."""
        return True

    def bonus(self, participant=None):
        """The bonus to be awarded to the given participant."""
        return 0

    def bonus_reason(self):
        """The reason offered to the participant for giving the bonus."""
        return "Thank for participating! Here is your bonus."

    def attention_check(self, participant=None):
        """Check if participant performed adequately."""
        return True

    def submission_successful(self, participant=None):
        pass

    def recruit(self):
        """Recruit participants to the experiment as needed."""
        if self.networks(full=False):
            self.log("Network space available: recruiting 1 more participant", "-----")
            self.recruiter().recruit_participants(n=1)
        else:
            self.log("All networks full: closing recruitment", "-----")
            self.recruiter().close_recruitment()

    def log(self, text, key="?????", force=False):
        if force or self.verbose:
            print ">>>> {} {}".format(key[0:5], text)
            sys.stdout.flush()

    def log_summary(self):
        """Log a summary of all the participants' status codes."""
        participants = Participant.query.with_entities(Participant.status).all()
        counts = Counter([p.status for p in participants])
        sorted_counts = sorted(counts.items(), key=itemgetter(0))
        self.log("Status summary: {}".format(str(sorted_counts)))
        return sorted_counts

    def save(self, *objects):
        """Add all the objects to the session and commit them."""
        from psiturk.db import db_session as session_psiturk
        if len(objects) > 0:
            self.session.add_all(objects)
        self.session.commit()
        session_psiturk.commit()

    def node_post_request(self, participant, node):
        pass

    def node_get_request(self, node, nodes):
        pass

    def vector_post_request(self, node, vectors):
        pass

    def vector_get_request(self, node, vectors):
        pass

    def info_post_request(self, node, info):
        pass

    def info_get_request(self, node, infos):
        pass

    def transmission_post_request(self, node, transmissions):
        pass

    def transmission_get_request(self, node, transmissions):
        pass

    def transformation_post_request(self, node, transformation):
        pass

    def transformation_get_request(self, node, transformations):
        pass
