from dallinger.nodes import Source
import random


class WarOfTheGhostsSource(Source):
    """A Source that reads in a random story from a file and transmits it."""

    __mapper_args__ = {
        "polymorphic_identity": "war_of_the_ghosts_source"
    }

    def _contents(self):
        """Define the contents of new Infos.

        transmit() -> _what() -> create_information() -> _contents().
        """
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
