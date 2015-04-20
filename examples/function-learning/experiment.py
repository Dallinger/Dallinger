import wallace
from wallace.agents import ReplicatorAgent
from wallace.models import Source
import random
import json
from sqlalchemy.ext.declarative import declared_attr
import math


class FunctionLearning(wallace.experiments.Experiment):
    def __init__(self, session):
        super(FunctionLearning, self).__init__(session)

        self.max_population_size = 10
        self.num_repeats = 4
        self.agent_type_generator = ReplicatorAgent
        self.network_type = wallace.networks.Chain
        self.process_type = wallace.processes.RandomWalkFromSource
        self.recruiter = wallace.recruiters.PsiTurkRecruiter

        # Get a list of all the networks, creating them if they don't already
        # exist.
        self.networks = wallace.models.Network.query.all()
        if not self.networks:
            for i in range(self.num_repeats):
                self.save(self.network_type())
        self.networks = wallace.models.Network.query.all()

        # Setup for first time experiment is accessed
        for net in self.networks:
            if not net.sources:
                source = SinusoidalFunctionSource()
                self.save(source)
                net.add(source)
                self.save()
                print source
                print "Added initial source: " + str(source)

    def information_creation_trigger(self, info):

        self.save(info.origin)

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment(self)
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)

    def is_network_full(self, network):
        return len(network.agents) >= self.max_population_size


class AbstractFnSource(Source):
    __abstract__ = True

    def create_information(self):
        info = wallace.models.Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._data())
        return info

    def _data(self):
        x_min = 1
        x_max = 100

        x_values = random.sample(xrange(x_min, x_max), 20)
        y_values = [self.func(x) for x in x_values]

        data = {"x": x_values, "y": y_values}

        return json.dumps(data)

    def _what(self):
        return self.create_information()

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
