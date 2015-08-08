"""The base experiment class."""

from wallace.models import Network, Node
from psiturk.db import db_session as session_psiturk
from psiturk.models import Participant
from wallace.nodes import Agent
from sqlalchemy import and_
import random
import inspect
import sys

from datetime import datetime


class Experiment(object):

    def log(self, text, key="?????"):
        if self.verbose:
            print ">>>> {} {}".format(key[0:5], text)
            sys.stdout.flush()

    def __init__(self, session):
        from recruiters import PsiTurkRecruiter
        self.verbose = True
        self.task = "Experiment title"
        self.session = session
        self.practice_repeats = 0
        self.experiment_repeats = 0
        self.recruiter = PsiTurkRecruiter
        self.initial_recruitment_size = 1

    def setup(self):
        """Create the networks if they don't already exist."""
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

    def newcomer_arrival_trigger(self, newcomer):
        pass

    def transmission_reception_trigger(self, transmissions):
        # Mark transmissions as received
        for t in transmissions:
            t.mark_received()

    def information_creation_trigger(self, info):
        pass

    def step(self):
        pass

    def create_agent_trigger(self, agent, network):
        network.add_agent(agent)
        self.process(network).step()

    def assign_agent_to_participant(self, participant_uuid):

        key = participant_uuid[0:5]

        networks_with_space = Network.query.filter_by(full=False).all()
        networks_participated_in = [node.network_uuid for node in Node.query.with_entities(Node.network_uuid).filter_by(participant_uuid=participant_uuid).all()]
        legal_networks = [net for net in networks_with_space if net.uuid not in networks_participated_in]

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
            self.log("Practice networks available. Assigning participant to practice network {}.".format(chosen_network.uuid), key)
        else:
            chosen_network = random.choice(legal_networks)
            self.log("No practice networks available. Assigning participant to experiment network {}".format(chosen_network.uuid), key)

        # Generate the right kind of newcomer and assign them to the network.
        self.log("Generating node", key)
        if inspect.isclass(self.agent):
            if issubclass(self.agent, Node):
                newcomer = self.agent(participant_uuid=participant_uuid, network=chosen_network)
            else:
                raise ValueError("{} is not a subclass of Node".format(self.agent))
        else:
            newcomer = self.agent(network=chosen_network)(participant_uuid=participant_uuid, network=chosen_network)

        self.log("Node {} successfully generated, recalculating if network is full".format(newcomer.uuid), key)
        chosen_network.calculate_full()

        self.log("running exp.create_agent_trigger", key)
        self.create_agent_trigger(agent=newcomer, network=chosen_network)

        self.log("exp.create_agent_trigger completed, returning node", key)
        return newcomer

    def participant_submission_trigger(
            self, participant=None):
        """Check performance and recruit new participants as needed."""
        # Check that the particpant's performance was acceptable.

        key = participant.uniqueid[0:5]
        assignment_id = participant.assignmentid
        participant_uuid = participant.uniqueid

        # Accept the HIT.
        self.log("Approving the assignment on mturk", key)
        self.recruiter().approve_hit(assignment_id)

        # Reward the bonus.
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

        self.log("Checking participant data", key)
        worked = self.check_participant_data(participant=participant)

        if not worked:
            self.log("Participant data check failed: failing nodes, setting status to 105, and recruiting replacement participant", key)

            for node in Node.query.filter_by(participant_uuid=participant_uuid).all():
                node.fail()
            self.save()

            participant.status = 105
            session_psiturk.commit()
            self.recruiter().recruit_participants(n=1)
        else:
            # check participant's performance
            self.log("Running participant attention check", key)
            attended = self.participant_attention_check(
                participant=participant)

            if not attended:
                self.log("Attention check failed: failing nodes, setting status to 102, and recruiting replacement participant", key)

                for node in Node.query.filter_by(participant_uuid=participant_uuid).all():
                    node.fail()
                self.save()

                participant.status = 102
                session_psiturk.commit()
                self.recruiter().recruit_participants(n=1)
            else:
                self.log("All checks passed: setting status to 101 and running recruit()", key)
                participant.status = 101
                session_psiturk.commit()
                self.recruit()

        participants = Participant.query.with_entities(Participant.status).all()
        statuses = [p.status for p in participants]
        status_set = set(statuses)
        key = "Summary:"
        self.log("printing status summary", key)
        for status in status_set:
            self.log("{} participants with status {}".format(len([s for s in statuses if s == status]), status), key)
        self.log("end of status summary", key)

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

    def check_participant_data(self, particpant=None):
        """Check the data is as it should be"""
        return True
