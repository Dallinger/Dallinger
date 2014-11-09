from wallace.agents import Source
from sqlalchemy.ext.declarative import declared_attr
import random
import json
import math


class AbstractFunctionSource(Source):
    __abstract__ = True

    def _data(self, length):
        x_min = 1
        x_max = 100

        x_values = random.sample(xrange(x_min, x_max), length)
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
