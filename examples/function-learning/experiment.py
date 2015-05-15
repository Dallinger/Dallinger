import wallace
from wallace.nodes import ReplicatorAgent, Source
from wallace.networks import Chain
from wallace import processes
from wallace.recruiters import PsiTurkRecruiter
import random
import json
from sqlalchemy.ext.declarative import declared_attr
import math


class FunctionLearning(wallace.experiments.Experiment):
    def __init__(self, session):
        super(FunctionLearning, self).__init__(session)

        self.num_repeats_experiment = 4
        self.agent = ReplicatorAgent
        self.network = lambda: Chain(max_size=2)
        self.recruiter = PsiTurkRecruiter
        self.setup()

        # Setup for first time experiment is accessed
        for net in self.networks:
            if not net.nodes(type=Source):
                source = SinusoidalFunctionSource()
                self.save(source)
                net.add_source(source)
                self.save()
                print source
                print "Added initial source: " + str(source)

    def create_agent_trigger(self, agent, network):
        network.add_agent(agent)
        processes.random_walk(network)


class AbstractFnSource(Source):
    __abstract__ = True

    def _contents(self):
        x_min = 1
        x_max = 100

        x_values = random.sample(xrange(x_min, x_max), 20)
        y_values = [self.func(x) for x in x_values]

        data = {"x": x_values, "y": y_values}

        return json.dumps(data)

    @declared_attr
    def __mapper_args__(cls):
        return {"polymorphic_identity": cls.__name__.lower()}


class IdentityFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return x


class AdditiveInverseFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return 100 - x


class SinusoidalFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return 50.5 + 49.5 * math.sin(math.pi / 2 + x / (5 * math.pi))


class RandomMappingFunctionSource(AbstractFnSource, Source):
    m = random.shuffle(range(1, 100))

    def func(self, x):
        return self.m[x - 1]


class StepFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return 75 if x >= 50 else 25


class ConstantFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return 50


class LogisticFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return 1 / (0.01 + math.exp(-0.092 * x))


class ExponentialFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return 100 * math.exp(-0.05 * x)


class TriangleWaveFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return 2 * (100 - x) if x >= 50 else 2 * x


class SquareWaveFunctionSource(AbstractFnSource, Source):
    def func(self, x):
        return 75 if (math.fmod(x, 50) <= 25) else 25
