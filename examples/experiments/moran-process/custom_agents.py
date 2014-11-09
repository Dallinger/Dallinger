import wallace
from custom_transformations import SubstitutionCipher


class SimulatedAgent(wallace.agents.Agent):
    """A simulated agent that applies a substitution cipher to the text."""

    __mapper_args__ = {"polymorphic_identity": "simulated_agent"}

    def update(self, info_in):

        # Apply the translation transformation.
        transformation1 = SubstitutionCipher(info_in=info_in, node=self)
        transformation1.apply()
