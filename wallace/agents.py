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
    __mapper_args__ = {"polymorphic_identity": "agent"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

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
            transmission.mark_received()
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
    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    ome_size = Column(Integer, default=8)

    @staticmethod
    def _data(length):
        return NotImplementedError

    @property
    def omes(self):
        return [self.ome]

    @property
    def ome(self):
        return Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._data(self.ome_size))

    def transmit(self, other_node):
        for ome in self.omes:
            super(Source, self).transmit(ome, other_node)

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
