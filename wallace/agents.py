from sqlalchemy import ForeignKey, Column, String, Integer, desc, Boolean
from sqlalchemy.ext.declarative import declared_attr
from datetime import datetime

from .models import Node, Info
from .information import Genome, Memome
import random
import json
import math

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def timenow():
    time = datetime.now()
    return time.strftime(DATETIME_FMT)


class Agent(Node):
    """Agents have genomes and memomes, and update their contents when faced.
    By default, agents transmit unadulterated copies of their genomes and
    memomes, with no error or mutation.
    """

    __tablename__ = "agent"
    __table_args__ = {"schema": "wallace"}
    __mapper_args__ = {"polymorphic_identity": "agent"}

    uuid = Column(
        String(32),
        ForeignKey("wallace.node.uuid"),
        primary_key=True)

    is_visible = Column(Boolean, unique=False, default=True)

    @property
    def omes(self):
        return [self.ome]

    @property
    def ome(self):
        ome = Info\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Info.creation_time))\
            .first()
        return ome

    def transmit(self, other_node):
        for ome in self.omes:
            super(Agent, self).transmit(ome, other_node)

    def broadcast(self):
        for vector in self.outgoing_vectors:
            self.transmit(vector.destination)

    def update(self, info):
        info.copy_to(self)

    def receive_all(self):
        pending_transmissions = self.pending_transmissions
        for transmission in pending_transmissions:
            transmission.receive_time = timenow()
            self.update(transmission.info)


class BiologicalAgent(Agent):

    __mapper_args__ = {"polymorphic_identity": "biological_agent"}

    @property
    def omes(self):
        return [self.genome, self.memome]

    @property
    def genome(self):
        genome = Genome\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Genome.creation_time))\
            .first()
        return genome

    @property
    def memome(self):
        memome = Memome\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Memome.creation_time))\
            .first()
        return memome


class Source(Node):
    __tablename__ = "source"
    __table_args__ = {"schema": "wallace"}
    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    uuid = Column(
        String(32),
        ForeignKey("wallace.node.uuid"),
        primary_key=True)

    genome_size = Column(Integer, default=8)
    memome_size = Column(Integer, default=8)

    @staticmethod
    def _data(length):
        return NotImplementedError

    def generate_genome(self):
        return Genome(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._data(self.genome_size))

    def generate_memome(self):
        return Memome(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._data(self.memome_size))

    def transmit(self, other_node):
        genome = self.generate_genome()
        super(Source, self).transmit(genome, other_node)

        memome = self.generate_memome()
        super(Source, self).transmit(memome, other_node)

    def broadcast(self):
        for vector in self.outgoing_vectors:
            self.transmit(vector.destination)


class RandomBinaryStringSource(Source):
    """An agent whose genome and memome are random binary strings. The source
    only transmits; it does not update.
    """

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    @staticmethod
    def _data(length):
        return "".join([str(random.randint(0, 1)) for i in range(length)])


class AbstractFunctionSource(Source):
    __abstract__ = True

    def _data(self, length):
        x_min = 1
        x_max = 100

        x_values = random.sample(xrange(x_min, x_max), length)
        y_values = [self.func(x) for x in x_values]

        return json.dumps(dict(zip(x_values, y_values)))

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
        return 50.5 + 49.5 * math.sin(math.pi/2 + x/(5*math.pi))


class RandomMappingFunctionSource(AbstractFunctionSource, Source):
    m = random.shuffle(range(1, 100))

    def func(self, x):
        return self.m[x-1]


class StepFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 75 if x >= 50 else 25


class ConstantFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 50


class LogisticFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 1/(0.01+math.exp(-0.092*x))


class ExponentialFunctionSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 100*math.exp(-0.05*x)


class TriangleWaveSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 2*(100-x) if x >= 50 else 2*x


class SquareWaveSource(AbstractFunctionSource, Source):
    def func(self, x):
        return 75 if (math.fmod(x, 50) <= 25) else 25
