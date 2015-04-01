from wallace.networks import Chain
from wallace.models import Info, Network
from wallace.processes import RandomWalkFromSource
from wallace.recruiters import PsiTurkRecruiter
from wallace.agents import ReplicatorAgent
from wallace.experiments import Experiment
from wallace.sources import Source
import random


class Bartlett1932(Experiment):
    def __init__(self, session):
        super(Bartlett1932, self).__init__(session)

        self.max_population_size = 10
        self.num_repeats = 4
        self.agent_type_generator = ReplicatorAgent
        self.network_type = Chain
        self.process_type = RandomWalkFromSource
        self.recruiter = PsiTurkRecruiter

        # Get a list of all the networks, creating them if they don't already
        # exist.
        self.networks = Network.query.all()
        if not self.networks:
            for i in range(self.num_repeats):
                net = self.network_type()
                self.session.add(net)
        self.networks = Network.query.all()

        # Setup for first time experiment is accessed
        for net in self.networks:
            if not net.sources:
                source = WarOfTheGhostsSource()
                self.session.add(source)
                self.session.commit()
                net.add_source(source)
                print source
                print "Added initial source: " + str(source)
                self.session.commit()

    def information_creation_trigger(self, info):

        agent = info.origin
        self.session.add(agent)
        self.session.commit()

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment(self)
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)

    def is_network_full(self, network):
        return len(network.agents) >= self.max_population_size


class WarOfTheGhostsSource(Source):
    """A source that transmits the War of Ghosts story from Bartlett (1932).
    """

    __mapper_args__ = {"polymorphic_identity": "war_of_the_ghosts_source"}

    def create_information(self):
        info = Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._story())
        return info

    def _story(self):
        stories = [
            "ghosts.md",
            "cricket.md",
            "moochi.md",
            "outwit.md",
            "raid.md",
            "species.md",
            "tennis.md",
            "vagabond.md"
        ]
        story = random.choice(stories)
        with open("static/stimuli/{}".format(story), "r") as f:
            return f.read()

    def _what(self):
        return self.create_information()
