from dallinger.information import Gene, Meme, State
from dallinger.nodes import Source, Agent, Environment
from dallinger import transformations
from sqlalchemy import Integer, Float
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import cast
from operator import attrgetter
import random


class LearningGene(Gene):
    """The Learning Gene."""

    __mapper_args__ = {"polymorphic_identity": "learning_gene"}

    def _mutated_contents(self):
        alleles = ["social", "asocial"]
        return random.choice([a for a in alleles if a != self.contents])


class RogersSource(Source):
    """A source that initializes agents as asocial learners."""

    __mapper_args__ = {"polymorphic_identity": "rogers_source"}

    def create_information(self):
        """Create a new learning gene."""
        if len(self.infos()) == 0:
            LearningGene(
                origin=self,
                contents="asocial")

    def _what(self):
        """Transmit a learning gene by default."""
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
            raise Exception("You are calculating the fitness of agent {}, "
                            .format(self.id) +
                            "but they already have a fitness")
        infos = self.infos()

        said_blue = ([i for i in infos if
                      isinstance(i, Meme)][0].contents == "blue")
        proportion = float(
            max(State.query.filter_by(network_id=self.network_id).all(),
                key=attrgetter('creation_time')).contents)
        self.proportion = proportion
        is_blue = proportion > 0.5

        if said_blue is is_blue:
            self.score = 1
        else:
            self.score = 0

        is_asocial = [
            i for i in infos if isinstance(i, LearningGene)
        ][0].contents == "asocial"
        e = 2
        b = 1
        c = 0.3 * b
        baseline = c + 0.0001

        self.fitness = (baseline + self.score * b - is_asocial * c) ** e

    def update(self, infos):
        """Process received infos."""
        for info_in in infos:
            if isinstance(info_in, LearningGene):
                if random.random() < 0.10:
                    self.mutate(info_in)
                else:
                    self.replicate(info_in)

    def _what(self):
        return self.infos(type=LearningGene)[0]


class RogersAgentFounder(RogersAgent):
    """The Rogers Agent Founder.

    It is like Rogers Agent except it cannot mutate.
    """

    __mapper_args__ = {"polymorphic_identity": "rogers_agent_founder"}

    def update(self, infos):
        """Process received infos."""
        for info in infos:
            if isinstance(info, LearningGene):
                self.replicate(info)


class RogersEnvironment(Environment):
    """The Rogers environment."""

    __mapper_args__ = {"polymorphic_identity": "rogers_environment"}

    def create_state(self, proportion):
        """Create an environmental state."""
        if random.random() < 0.5:
            proportion = 1 - proportion
        State(origin=self, contents=proportion)

    def step(self):
        """Prompt the environment to change."""
        current_state = max(self.infos(type=State),
                            key=attrgetter('creation_time'))
        current_contents = float(current_state.contents)
        new_contents = 1 - current_contents
        info_out = State(origin=self, contents=new_contents)
        transformations.Mutation(info_in=current_state, info_out=info_out)
