"""The base experiment class."""

from wallace.models import Network, Node
from wallace.nodes import Agent
from sqlalchemy import and_
import random
import inspect

from datetime import datetime


class Experiment(object):

    def __init__(self, session):
        from recruiters import PsiTurkRecruiter
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

        networks_with_space = Network.query.filter_by(full=False).all()
        networks_participated_in = [node.network_uuid for node in Node.query.with_entities(Node.network_uuid).filter_by(participant_uuid=participant_uuid).all()]
        legal_networks = [net for net in networks_with_space if net.uuid not in networks_participated_in]

        print ">>>>     {} networks out of {} remain available to participant {}"\
            .format(len(legal_networks),
                    (self.practice_repeats + self.experiment_repeats),
                    participant_uuid)

        if not legal_networks:
            return None

        legal_practice_networks = [net for net in legal_networks if net.role == "practice"]
        if legal_practice_networks:
            chosen_network = legal_practice_networks[0]
            print ">>>>     practice networks available. Assigning participant to practice network {}.".format(chosen_network.uuid)
        else:
            chosen_network = random.choice(legal_networks)
            print ">>>>     no practice networks available. Assigning participant to experiment network {}".format(chosen_network.uuid)

        # Generate the right kind of newcomer and assign them to the network.
        print ">>>>     generating node"
        if inspect.isclass(self.agent):
            if issubclass(self.agent, Node):
                newcomer = self.agent(participant_uuid=participant_uuid, network=chosen_network)
            else:
                raise ValueError("{} is not a subclass of Node".format(self.agent))
        else:
            newcomer = self.agent(network=chosen_network)(participant_uuid=participant_uuid, network=chosen_network)
        print ">>>>     participant {} has been assigned node {}".format(participant_uuid, newcomer.uuid)

        chosen_network.calculate_full()
        print ">>>>     running create_agent_trigger"
        self.create_agent_trigger(agent=newcomer, network=chosen_network)
        print ">>>>     create_agent_trigger completed"
        return newcomer

    def participant_completion_trigger(
            self, participant_uuid=None, assignment_id=None):
        """Check performance and recruit new participants as needed."""
        # Check that the particpant's performance was acceptable.

        print "Running completion trigger for participant {}."

        attended = self.participant_attention_check(
            participant_uuid=participant_uuid)

        # Accept the HIT.
        self.recruiter().approve_hit(assignment_id)

        # Reward the bonus.
        self.recruiter().reward_bonus(
            assignment_id,
            self.bonus(participant_uuid=participant_uuid),
            self.bonus_reason())

        # Recruit new participants as needed.
        if attended:
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
