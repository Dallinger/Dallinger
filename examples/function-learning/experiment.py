from wallace.networks import Chain
from wallace.processes import RandomWalkFromSource
from wallace.recruiters import PsiTurkRecruiter
from wallace.agents import ReplicatorAgent
from wallace.experiments import Experiment
from wallace.sources import Source
import random
import json
from sqlalchemy.ext.declarative import declared_attr
import math


class FunctionLearning(Experiment):
    def __init__(self, session):
        super(FunctionLearning, self).__init__(session)

        self.task = "Transmission chain"
        self.num_agents = 10
        self.num_steps = self.num_agents - 1
        self.agent_type = ReplicatorAgent
        self.network = Chain(self.agent_type, self.session)
        self.process = RandomWalkFromSource(self.network)
        self.recruiter = PsiTurkRecruiter

        # Setup for first time experiment is accessed
        if not self.network.sources:
            source = SinusoidalFunctionSource()
            self.network.add_source_global(source)
            print "Added initial source: " + str(source)

    def newcomer_arrival_trigger(self, newcomer):

        self.network.add_agent(newcomer)

        # If this is the first participant, link them to the source.
        if len(self.network) == 1:
            source = self.network.sources[0]
            source.connect_to(newcomer)
            self.network.db.commit()

        # Run the next step of the process.
        self.process.step()

    def transmission_reception_trigger(self, transmissions):
        # Mark transmissions as received
        for t in transmissions:
            t.mark_received()

    def information_creation_trigger(self, info):

        agent = info.origin
        self.network.db.add(agent)
        self.network.db.commit()

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment(self)
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)

    def is_experiment_over(self):
        return len(self.network.links) == self.num_agents


class AbstractFunctionSource(Source):
    __abstract__ = True

    def _data(self):
        x_min = 1
        x_max = 100

        x_values = random.sample(xrange(x_min, x_max), 20)
        y_values = [self.func(x) for x in x_values]

        data = {"x": x_values, "y": y_values}

        return json.dumps(data)

    @declared_attr
    def __mapper_args__(cls):
        return {"polymorphic_identity": cls.__name__.lower()}


class IdentityFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return x


class AdditiveInverseFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 100 - x


class SinusoidalFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 50.5 + 49.5 * math.sin(math.pi / 2 + x / (5 * math.pi))


class RandomMappingFunctionSource(AbstractFunctionSource, Source):
    m = random.shuffle(range(1, 100))

    def func(self, x):
        return self.m[x - 1]


class StepFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 75 if x >= 50 else 25


class ConstantFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 50


class LogisticFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 1 / (0.01 + math.exp(-0.092 * x))


class ExponentialFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 100 * math.exp(-0.05 * x)


class TriangleWaveFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 2 * (100 - x) if x >= 50 else 2 * x


class SquareWaveFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 75 if (math.fmod(x, 50) <= 25) else 25
