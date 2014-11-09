import wallace


class WarOfTheGhostsSource(wallace.sources.Source):
    """A source that transmits the War of Ghosts story from Bartlett (1932).
    """

    __mapper_args__ = {"polymorphic_identity": "war_of_the_ghosts_source"}

    @staticmethod
    def _data(length):
        with open("static/stimuli/ghosts.md", "r") as f:
            return f.read()
