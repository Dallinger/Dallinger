"""The base experiment class."""

from wallace.models import Network, Node, Info
from sqlalchemy import and_
import random
import inspect
import sys
from collections import Counter
from operator import itemgetter


class Experiment(object):

    def log(self, text, key="?????"):
        if self.verbose:
            print ">>>> {} {}".format(key[0:5], text)
            sys.stdout.flush()

    def log_summary(self):
        """Log a summary of all the participants' status codes."""
        from psiturk.models import Participant
        participants = Participant.query.with_entities(Participant.status).all()
        counts = Counter([p.status for p in participants])
        sorted_counts = sorted(counts.items(), key=itemgetter(0))
        self.log("Status summary: {}".format(str(sorted_counts)))
        return sorted_counts

    def __init__(self, session):
        from recruiters import PsiTurkRecruiter
        self.verbose = True
        self.task = "Experiment title"
        self.session = session
        self.practice_repeats = 0
        self.experiment_repeats = 0
        self.recruiter = PsiTurkRecruiter
        self.initial_recruitment_size = 1
        self.trusted_strings = ["Info", "Gene", "Meme", "State", "Node", "Agent", "Source", "Environment"]

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

    def save(self, *objects):
        """Add all the objects to the session and commit them."""
        if len(objects) > 0:
            self.session.add_all(objects)
        self.session.commit()

    def participant_submission_trigger(
            self, participant=None):
        """Run all post-processing code when an Assignment Submitted notification arrives"""
        from psiturk.db import db_session as session_psiturk

        key = participant.uniqueid[0:5]
        assignment_id = participant.assignmentid
        participant_id = participant.uniqueid

        # Approve the assignment.
        self.log("Approving the assignment on mturk", key)
        self.recruiter().approve_hit(assignment_id)

        # Check that the participant's data is okay...
        self.log("Checking participant data", key)
        worked = self.check_participant_data(participant=participant)

        # ... if not, fail their nodes.
        if not worked:
            self.log("Participant failed data check: failing nodes, setting status to 105, and recruiting replacement participant", key)

            participant.status = 105
            session_psiturk.commit()

            for node in Node.query.filter_by(participant_id=participant_id, failed=False).all():
                node.fail()
            self.save()

            self.recruiter().recruit_participants(n=1)
        else:
            # if their data is ok, pay them a bonus
            # note that the bonus is paid before the attention check
            self.log("Calculating bonus", key)
            bonus = self.bonus(participant=participant)
            if bonus >= 0.01:
                self.log("Bonus >= 0.01: paying bonus", key)
                self.recruiter().reward_bonus(
                    assignment_id,
                    bonus,
                    self.bonus_reason())
            else:
                self.log("bonus < 0.01: not paying bonus", key)

            # now perform an attention check
            self.log("Running participant attention check", key)
            attended = self.participant_attention_check(
                participant=participant)

            # if they fail the attention check fail their nodes and replace them
            if not attended:
                self.log("Attention check failed: failing nodes, setting status to 102, and recruiting replacement participant", key)

                participant.status = 102
                session_psiturk.commit()

                for node in Node.query.filter_by(participant_id=participant_id, failed=False).all():
                    node.fail()
                self.save()

                self.recruiter().recruit_participants(n=1)
            else:
                # otherwise everything is good
                # recruit is run to see if it is time to recruit more participants
                self.log("All checks passed: setting status to 101 and running recruit()", key)
                participant.status = 101
                session_psiturk.commit()
                self.participant_submission_success_trigger(participant=participant)
                self.save()
                self.recruit()

        self.log_summary()

    def participant_submission_success_trigger(self, participant=None):
        pass

    def recruit(self):
        """Recruit participants to the experiment as needed."""
        if self.networks(full=False):
            self.log("Network space available: recruiting 1 more participant", "-----")
            self.recruiter().recruit_participants(n=1)
        else:
            self.log("All networks full: closing recruitment", "-----")
            self.recruiter().close_recruitment()

    def bonus(self, participant=None):
        """The bonus to be awarded to the given participant."""
        return 0

    def bonus_reason(self):
        """The reason offered to the participant for giving the bonus."""
        return "Thank for participating! Here is your bonus."

    def participant_attention_check(self, participant=None):
        """Check if participant performed adequately."""
        return True

    def check_participant_data(self, participant=None):
        """Check that the data are acceptable."""
        return True

    ### METHODS TRIGGERED BY REQUESTS TO ROUTES IN CUSTOM ###

    def node_get_request(self, participant_id, node_id, type, failed, connection):
        key = participant_id[0:5]

        node = Node.query.get(node_id)
        self.log("Getting neighbors of node {}, type = {}, failed = {}, connection = {}".format(node_id, type, failed, connection), key)
        return node.neighbours(type=type, failed=failed, connection=connection)

    def node_post_request(self, participant_id):
        key = participant_id[0:5]

        self.log("Getting network for participant", key)
        network = self.get_network_for_participant(participant_id=participant_id)
        if network is None:
            return None

        self.log("Creating node", key)
        node = self.make_node_for_participant(participant_id=participant_id, network=network)

        if node is not None:
            self.log("Adding node to network", key)
            self.add_node_to_network(participant_id=participant_id, node=node, network=network)

        self.log("Returning node", key)
        return node

    def transmission_get_request(self, participant_id, node_id, direction, status):
        key = participant_id[0:5]

        node = Node.query.get(node_id)
        self.log("Getting transmissions", key)
        transmissions = node.transmissions(direction=direction, status=status)

        if (direction == "incoming" or direction == "all") and (status == "pending" or status == "all"):
            self.log("Marking new transmissions as received", key)
            node.receive()

        self.log("Returning transmissions", key)
        return transmissions

    def transmission_post_request(self, participant_id, node_id, info_id, destination_id):
        key = participant_id[0:5]

        origin = Node.query.get(node_id)

        if info_id is None and destination_id is None:
            self.log("Transmitting", key)
            return origin.transmit()
        elif info_id is None and destination_id is not None:
            destination = Node.query.get(node_id)
            self.log("Transmitting", key)
            return origin.transmit(to_whom=destination)
        elif info_id is not None and destination_id is None:
            info = Info.query.get(info_id)
            self.log("Transmitting", key)
            return origin.transmit(what=info)
        else:
            destination = Node.query.get(node_id)
            info = Info.query.get(info_id)
            self.log("Transmitting", key)
            return origin.transmit(what=info, to_whom=destination)

    def info_get_request(self, participant_id, node_id, type, info_id):
        key = participant_id[0:5]

        node = Node.query.get(node_id)
        self.log("Gettings infos", key)
        if info_id is None:
            return node.infos(type=type)
        else:
            info_id = int(info_id)
            requested_info = Info.query.get(info_id)
            if requested_info.origin_id == node_id:
                return [requested_info]
            elif info_id in [t.info_id for t in node.transmissions(direction="incoming", status="received")]:
                return [requested_info]
            else:
                return []

    def info_post_request(self, participant_id, node_id, type, contents):
        key = participant_id[0:5]

        node = Node.query.get(node_id)
        self.log("Making info", key)
        info = type(origin=node, contents=contents)
        return info


    ### SUPPORT METHODS CALLED BY METHODS CALLED BY REQUESTS ###

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

    def make_node_for_participant(self, participant_id, network):
        key = participant_id[0:5]
        if inspect.isclass(self.agent):
            if issubclass(self.agent, Node):
                node = self.agent(participant_id=participant_id, network=network)
            else:
                raise ValueError("{} is not a subclass of Node".format(self.agent))
        else:
            from psiturk.models import Participant
            participant = Participant.query.filter_by(uniqueid=participant_id).all()[0]
            if participant.status in [1, 2]:
                node = self.agent(network=network)(participant_id=participant_id, network=network)
            else:
                self.log("Participant status = {}, node creation aborted".format(participant.status), key)
                return None

        self.log("Node successfully generated, recalculating if network is full", key)
        network.calculate_full()
        return node

    def add_node_to_network(self, participant_id, node, network):
        network.add_node(node)

    def receive_transmissions(self, transmissions):
        for t in transmissions:
            t.mark_received()

    def evaluate(self, string):
        if string in self.trusted_strings:
            return eval(string)
        else:
            raise ValueError("Cannot evaluate {}: not a trusted string".format(string))
