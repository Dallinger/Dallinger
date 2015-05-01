"""Bartlett's trasmission chain experiment from Remembering (1932)."""

from wallace.networks import Chain
from wallace.models import Info, Agent, Source
from wallace.processes import RandomWalkFromSource
from wallace.agents import ReplicatorAgent
from wallace.experiments import Experiment
import random


class Bartlett1932(Experiment):

    def __init__(self, session):

        super(Bartlett1932, self).__init__(session)

        self.num_repeats_experiment = 1
        self.num_repeats_practice = 0
        self.agent_type_generator = ReplicatorAgent
        self.process = RandomWalkFromSource
        self.network = lambda: Chain(max_size=3)
        self.setup()

        # Setup for first time experiment is accessed
        for net in self.networks:
            if not net.nodes(type=Source):
                source = WarOfTheGhostsSource()
                self.save(source)
                net.add_source(source)
                self.save()

    def participant_completion_trigger(self):

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment(self)
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)


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
