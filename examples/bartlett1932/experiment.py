"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from wallace.networks import Chain
from wallace.models import Info, Network, Agent, Source
from wallace.processes import RandomWalkFromSource
from wallace.recruiters import PsiTurkRecruiter
from wallace.agents import ReplicatorAgent
from wallace.experiments import Experiment
import random


class Bartlett1932(Experiment):
    def __init__(self, session):
        super(Bartlett1932, self).__init__(session)

        self.max_population_size = 10
        self.num_repeats_experiment = 4
        self.num_repeats_practice = 2
        self.agent_type_generator = ReplicatorAgent
        self.network_type = Chain
        self.process_type = RandomWalkFromSource
        self.recruiter = PsiTurkRecruiter

        # Get a list of all the networks, creating them if they don't already
        # exist.
        self.networks = Network.query.all()
        if not self.networks:
            for i in range(self.num_repeats_experiment + self.num_repeats_practice):
                self.save(self.network_type())
        self.networks = Network.query.all()

        # Setup for first time experiment is accessed
        for net in self.networks:
            if not net.nodes(type=Source):
                source = WarOfTheGhostsSource()
                self.save(source)
                net.add_source(source)
                self.save()
                #print source
                #print "Added initial source: " + str(source)

    def information_creation_trigger(self, info):

        self.save(info.origin)

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment(self)
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)

    def is_network_full(self, network):
        """The network is full when it reaches its maximum size."""
        return len(network.nodes(type=Agent)) >= self.max_population_size


class WarOfTheGhostsSource(Source):

    """Transmit the War of Ghosts story from Bartlett (1932)."""

    __mapper_args__ = {"polymorphic_identity": "war_of_the_ghosts_source"}

    def create_information(self):
        """Create an info whose contents is a story."""
        info = Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._story())
        return info

    def _story(self):
        """Return the text of a story from Bartlett (1932)."""
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
