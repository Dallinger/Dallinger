"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from wallace.networks import Chain
from wallace.nodes import Source, Agent
from wallace import processes
from wallace.experiments import Experiment
import random


class Bartlett1932(Experiment):

    """Defines the experiment."""

    def __init__(self, session):
        """Set up the initial networks."""
        super(Bartlett1932, self).__init__(session)

        self.practice_repeats = 0
        self.experiment_repeats = 1
        self.agent = Agent
        self.network = lambda: Chain(max_size=3)

        self.setup()

    def setup(self):
        """Setup for first time experiment is accessed."""
        if not self.networks():
            super(Bartlett1932, self).setup()
            for net in self.networks():
                if not net.nodes(type=Source):
                    source = WarOfTheGhostsSource(network=net)
                    net.add_source(source)
            self.save()

    def add_node_to_network(self, participant, node, network):
        """When an agent is created, add it to the network and take a step."""
        network.add_node(node)
        processes.random_walk(network)
        node.receive()

    def recruit(self):
        """Recruit participants to the experiment as needed."""
        if self.networks(full=False):
            self.recruiter().recruit_participants(n=1)
        else:
            self.recruiter().close_recruitment()


class WarOfTheGhostsSource(Source):

    """Transmit a story from Bartlett (1932)."""

    __mapper_args__ = {"polymorphic_identity": "war_of_the_ghosts_source"}

    def _contents(self):
        """Read the markdown source of the story from a file."""
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
