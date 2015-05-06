"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from wallace.networks import Chain
from wallace.models import Info, Source
from wallace import processes
from wallace.agents import ReplicatorAgent
from wallace.experiments import Experiment
import random


class Bartlett1932(Experiment):

    def __init__(self, session):

        super(Bartlett1932, self).__init__(session)

        self.practice_repeats = 0
        self.experiment_repeats = 1
        self.agent = ReplicatorAgent
        self.network = lambda: Chain(max_size=3)
        self.setup()

        # Setup for first time experiment is accessed
        for net in self.networks():
            if not net.nodes(type=Source):
                source = WarOfTheGhostsSource()
                self.save(source)
                net.add_source(source)
                self.save()

    def create_agent_trigger(self, agent, network):
        network.add_agent(agent)
        processes.random_walk(network)

    def bonus(self, participant_uuid=None):
        """Compute the bonus for the given participant.
        This is called automatically when a participant finishes,
        it is called immediately prior to the participant_completion_trigger"""
        return 1


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
