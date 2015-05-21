"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from wallace.networks import Chain
from wallace.nodes import Source, ReplicatorAgent
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
        self.agent = ReplicatorAgent
        self.network = lambda: Chain(max_size=3)

        if not self.networks():
            self.setup()
        self.save()

    def setup(self):
        super(Bartlett1932, self).setup()
        # Setup for first time experiment is accessed
        for net in self.networks():
            if not net.nodes(type=Source):
                source = WarOfTheGhostsSource(network=net)
                net.add_source(source)

    def create_agent_trigger(self, agent, network):
        """When an agent is created, add it to the network and take a step."""
        network.add_agent(agent)
        processes.random_walk(network)

    def recruit(self):
        """Recruit participants to the experiment if needed."""
        self.recruiter().recruit_participants(n=1)

    def bonus(self, participant_uuid=None):
        """Compute the bonus for the given participant.

        This is called automatically when a participant finishes,
        it is called immediately prior to the participant_completion_trigger
        """
        return 1


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
