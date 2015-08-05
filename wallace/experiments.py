"""The base experiment class."""

from wallace.models import Network, Node
from psiturk.models import Participant
from wallace.nodes import Agent
from sqlalchemy import and_
import random
import inspect
import sys

from datetime import datetime


class Experiment(object):

    def log(self, text):
        if self.verbose:
            print ">>>> {}".format(text)
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
            if self.verbose:
                print ">>>>{}   No networks available, returning None".format(key)
            return None

        if self.verbose:
            print ">>>>{}   {} networks out of {} available to participant"\
                .format(key, len(legal_networks),
                        (self.practice_repeats + self.experiment_repeats))

        legal_practice_networks = [net for net in legal_networks if net.role == "practice"]
        if legal_practice_networks:
            chosen_network = legal_practice_networks[0]
            if self.verbose:
                print ">>>>{}   Practice networks available. Assigning participant to practice network {}.".format(key, chosen_network.uuid)
        else:
            chosen_network = random.choice(legal_networks)
            if self.verbose:
                print ">>>>{}   No practice networks available. Assigning participant to experiment network {}".format(key, chosen_network.uuid)

        # Generate the right kind of newcomer and assign them to the network.
        if self.verbose:
            print ">>>>{}   Generating node".format(key)
        if inspect.isclass(self.agent):
            if issubclass(self.agent, Node):
                newcomer = self.agent(participant_uuid=participant_uuid, network=chosen_network)
            else:
                raise ValueError("{} is not a subclass of Node".format(self.agent))
        else:
            newcomer = self.agent(network=chosen_network)(participant_uuid=participant_uuid, network=chosen_network)
        if self.verbose:
            print ">>>>{}   Node successfully generated".format(key, newcomer.uuid)
            print ">>>>{}   Re-calculcating if network is full".format(key)

        chosen_network.calculate_full()
        if self.verbose:
            print ">>>>{}   running exp.create_agent_trigger".format(key)
        self.create_agent_trigger(agent=newcomer, network=chosen_network)
        if self.verbose:
            print ">>>>{}   exp.create_agent_trigger completed".format(key)
        return newcomer

    def participant_submission_trigger(
            self, participant_uuid=None, assignment_id=None):
        """Check performance and recruit new participants as needed."""
        # Check that the particpant's performance was acceptable.

        key = participant_uuid[0:5]

        # Accept the HIT.
        log("{} Approving the assignment on mturk".format(key))
        self.recruiter().approve_hit(assignment_id)

        # Reward the bonus.
        log("{} Awarding bonus".format(key))
        self.recruiter().reward_bonus(
            assignment_id,
            self.bonus(participant_uuid=participant_uuid),
            self.bonus_reason())

        # check participant's performance
        log("{}   Running participant attention check".format(key))
        attended = self.participant_attention_check(
            participant_uuid=participant_uuid)

        participant = Participant.query.filter_by(uniqueid=participant_uuid).one()
        if not attended:
            log("{} Attention check failed: failing nodes, setting status to 102, and re-recruiting participant".format(key))

            for node in Node.query.filter_by(participant_uuid=participant_uuid).all():
                node.fail()

            participant.status = 102
            self.recruiter().recruit_participants(n=1)
        else:
            log("{} Attention check passed: setting status to 101 and running recruit()".format(key))
            participant.status = 101
            self.recruit()

    def recruit(self):
        """Recruit participants to the experiment as needed."""
        if self.networks(full=False):
            self.recruiter().recruit_participants(n=1)
        else:
            self.recruiter().close_recruitment()

    def bonus(self, participant_uuid=None):
        """The bonus to be awarded to the given participant."""
        return 0

    def bonus_reason(self):
        """The reason offered to the participant for giving the bonus."""
        return "Thank for participating! Here is your bonus."

    def participant_attention_check(self, participant_uuid=None):
        """Check if participant performed adequately."""
        return True
