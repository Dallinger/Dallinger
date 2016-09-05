"""Define a transmission-chain experiment that transmits functional forms."""

from dallinger.experiments import Experiment
from dallinger.nodes import Source
from dallinger.networks import Chain
import random
import json
from sqlalchemy.ext.declarative import declared_attr
import math


class FunctionLearning(Experiment):
    """A function-learning experiment."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in dallinger).

        A few properties are then overwritten. Finally, setup() is called.
        """
        super(FunctionLearning, self).__init__(session)
        self.source = SinusoidalFunctionSource
        self.experiment_repeats = 1
        self.setup()

    def setup(self):
        """Setup does stuff only if there are no networks.

        This is so it only runs once at the start of the experiment. It first
        calls the same function in the super (see experiments.py in dallinger).
        Then it adds a source to each network.
        """
        if not self.networks():
            super(FunctionLearning, self).setup()
            for net in self.networks():
                self.source(network=net)

    def create_network(self):
        """Create a new network."""
        return Chain(max_size=3)

    def add_node_to_network(self, node, network):
        """When an agent is created, add it to the network and take a step."""
        network.add_node(node)
        parent = node.neighbors(direction="from")[0]
        parent.transmit()
        node.receive()


class AbstractFnSource(Source):
    """Abstract class for sources that send functions."""

    __abstract__ = True

    def _contents(self):
        x_min = 1
        x_max = 100

        x_values = random.sample(xrange(x_min, x_max), 20)
        y_values = [self._func(x) for x in x_values]

        data = {"x": x_values, "y": y_values}

        return json.dumps(data)

    @declared_attr
    def __mapper_args__(cls):
        """The name of the source is derived from its class name."""
        return {
            "polymorphic_identity": cls.__name__.lower()
        }


class IdentityFunctionSource(AbstractFnSource, Source):
    """A source that transmits the identity function."""

    def _func(self, x):
        return x


class AdditiveInverseFunctionSource(AbstractFnSource, Source):
    """A source that transmits the identity function."""

    def _func(self, x):
        return 100 - x


class SinusoidalFunctionSource(AbstractFnSource, Source):
    """A source that transmits a sinusoidal function."""

    def _func(self, x):
        return 50.5 + 49.5 * math.sin(math.pi / 2 + x / (5 * math.pi))


class RandomMappingFunctionSource(AbstractFnSource, Source):
    """A source that transmits a random mapping of x to y values."""

    m = random.shuffle(range(1, 100))

    def _func(self, x):
        return self.m[x - 1]


class StepFunctionSource(AbstractFnSource, Source):
    """A source that transmits a step function."""

    def _func(self, x):
        return 75 if x >= 50 else 25


class ConstantFunctionSource(AbstractFnSource, Source):
    """A source that transmits a constant function."""

    def _func(self, x):
        return 50


class LogisticFunctionSource(AbstractFnSource, Source):
    """A source that transmits a logistic function."""

    def _func(self, x):
        return 1 / (0.01 + math.exp(-0.092 * x))


class ExponentialFunctionSource(AbstractFnSource, Source):
    """A source that transmits an exponential function."""

    def _func(self, x):
        return 100 * math.exp(-0.05 * x)


class TriangleWaveFunctionSource(AbstractFnSource, Source):
    """A source that transmits a sawtooth wave function."""

    def _func(self, x):
        return 2 * (100 - x) if x >= 50 else 2 * x


class SquareWaveFunctionSource(AbstractFnSource, Source):
    """A source that transmits a square-wave function."""

    def _func(self, x):
        return 75 if (math.fmod(x, 50) <= 25) else 25
