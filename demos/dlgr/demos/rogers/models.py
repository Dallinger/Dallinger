from operator import attrgetter
import random

from sqlalchemy import Float, Integer
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import cast

from dallinger.models import Transformation
from dallinger.information import Gene, Meme, State
from dallinger.nodes import Agent, Source


class LearningGene(Gene):
    """The Learning Gene."""

    __mapper_args__ = {"polymorphic_identity": "learning_gene"}

    def _mutated_contents(self):
        # Toggle between the two possibilities
        if self.contents == "social":
            return "asocial"
        else:
            return "social"


class RogersSource(Source):
    """A source that initializes agents as asocial learners."""

    __mapper_args__ = {"polymorphic_identity": "rogers_source"}

    def _info_type(self):
        """Create a learning gene by default."""
        return LearningGene

    def _contents(self):
        """Contents of created Infos is 'asocial' by default."""
        return "asocial"

    def _what(self):
        """Transmit the first learning gene by default."""
        return self.infos(type=LearningGene)[0]


class RogersAgent(Agent):
    """The Rogers Agent."""

    __mapper_args__ = {"polymorphic_identity": "rogers_agent"}

    @hybrid_property
    def generation(self):
        """Convert property2 to genertion."""
        return int(self.property2)

    @generation.setter
    def generation(self, generation):
        """Make generation settable."""
        self.property2 = repr(generation)

    @generation.expression
    def generation(self):
        """Make generation queryable."""
        return cast(self.property2, Integer)

    @hybrid_property
    def score(self):
        """Convert property3 to score."""
        return int(self.property3)

    @score.setter
    def score(self, score):
        """Mark score settable."""
        self.property3 = repr(score)

    @score.expression
    def score(self):
        """Make score queryable."""
        return cast(self.property3, Integer)

    @hybrid_property
    def proportion(self):
        """Make property4 proportion."""
        return float(self.property4)

    @proportion.setter
    def proportion(self, proportion):
        """Make proportion settable."""
        self.property4 = repr(proportion)

    @proportion.expression
    def proportion(self):
        """Make proportion queryable."""
        return cast(self.property4, Float)

    def calculate_fitness(self):
        """Calculcate your fitness."""
        if self.fitness is not None:
            raise Exception(
                "You are calculating the fitness of agent {}, ".format(self.id)
                + "but they already have a fitness"
            )

        said_blue = self.infos(type=Meme)[0].contents == "blue"

        proportion = float(
            max(
                self.network.nodes(type=RogersEnvironment)[0].infos(),
                key=attrgetter("id"),
            ).contents
        )
        self.proportion = proportion
        is_blue = proportion > 0.5

        if said_blue is is_blue:
            self.score = 1
        else:
            self.score = 0

        is_asocial = self.infos(type=LearningGene)[0].contents == "asocial"

        e = 2
        b = 1
        c = 0.3 * b
        baseline = c + 0.0001

        self.fitness = (baseline + self.score * b - is_asocial * c) ** e

    def update(self, infos):
        """Process received infos."""
        genes = [i for i in infos if isinstance(i, LearningGene)]
        for gene in genes:
            if (
                self.network.role == "experiment"
                and self.generation > 0
                and random.random() < 0.10
            ):
                self.mutate(gene)
            else:
                self.replicate(gene)

    def _what(self):
        return self.infos(type=LearningGene)[0]


class RogersEnvironment(Source):
    """The Rogers environment."""

    __mapper_args__ = {"polymorphic_identity": "rogers_environment"}

    @hybrid_property
    def proportion(self):
        """Convert property1 to propoertion."""
        return float(self.property1)

    @proportion.setter
    def proportion(self, proportion):
        """Make proportion settable."""
        self.property1 = repr(proportion)

    @proportion.expression
    def proportion(self):
        """Make proportion queryable."""
        return cast(self.property1, Float)

    def _info_type(self):
        """By default create States."""
        return State

    def _contents(self):
        """Contents of created infos is either propirtion or 1-proportion by default."""
        if random.random() < 0.5:
            return self.proportion
        else:
            return 1 - self.proportion

    def _what(self):
        """By default transmit the most recent state"""
        return max(self.infos(type=State), key=attrgetter("id"))

    def step(self):
        """Prompt the environment to change."""
        current_state = max(self.infos(type=State), key=attrgetter("id"))
        current_contents = float(current_state.contents)
        new_contents = 1 - current_contents
        info_out = State(origin=self, contents=new_contents)
        Transformation(info_in=current_state, info_out=info_out)
