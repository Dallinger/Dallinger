import json
import math
import random

from sqlalchemy.ext.declarative import declared_attr

from dallinger.nodes import Source


class AbstractFnSource(Source):
    """Abstract class for sources that send functions."""

    __abstract__ = True

    def _contents(self):
        x_min = 1
        x_max = 100

        x_values = random.sample(range(x_min, x_max), 20)
        y_values = [self._func(x) for x in x_values]

        data = {"x": x_values, "y": y_values}

        return json.dumps(data)

    @declared_attr
    def __mapper_args__(cls):
        """The name of the source is derived from its class name."""
        return {"polymorphic_identity": cls.__name__.lower()}


class IdentityFunctionSource(AbstractFnSource):
    """A source that transmits the identity function."""

    def _func(self, x):
        return x


class AdditiveInverseFunctionSource(AbstractFnSource):
    """A source that transmits the identity function."""

    def _func(self, x):
        return 100 - x


class SinusoidalFunctionSource(AbstractFnSource):
    """A source that transmits a sinusoidal function."""

    def _func(self, x):
        return 50.5 + 49.5 * math.sin(math.pi / 2 + x / (5 * math.pi))


class RandomMappingFunctionSource(AbstractFnSource):
    """A source that transmits a random mapping of x to y values."""

    m = random.shuffle(list(range(1, 100)))

    def _func(self, x):
        return self.m[x - 1]


class StepFunctionSource(AbstractFnSource):
    """A source that transmits a step function."""

    def _func(self, x):
        return 75 if x >= 50 else 25


class ConstantFunctionSource(AbstractFnSource):
    """A source that transmits a constant function."""

    def _func(self, x):
        return 50


class LogisticFunctionSource(AbstractFnSource):
    """A source that transmits a logistic function."""

    def _func(self, x):
        return 1 / (0.01 + math.exp(-0.092 * x))


class ExponentialFunctionSource(AbstractFnSource):
    """A source that transmits an exponential function."""

    def _func(self, x):
        return 100 * math.exp(-0.05 * x)


class TriangleWaveFunctionSource(AbstractFnSource):
    """A source that transmits a sawtooth wave function."""

    def _func(self, x):
        return 2 * (100 - x) if x >= 50 else 2 * x


class SquareWaveFunctionSource(AbstractFnSource):
    """A source that transmits a square-wave function."""

    def _func(self, x):
        return 75 if (math.fmod(x, 50) <= 25) else 25
