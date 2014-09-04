from sqlalchemy import ForeignKey, Column, String, Integer, desc

from .models import Node
from .memes import Genome, Memome

import numpy as np


class Agent(Node):
    """Agents have genomes and memomes, and update their contents when faced.
    By default, agents transmit unadulterated copies of their genomes and
    memomes, with no error or mutation.
    """

    __tablename__ = "agent"
    __mapper_args__ = {"polymorphic_identity": "agent"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

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

    def transmit(self, other_node):
        super(Agent, self).transmit(self.genome, other_node)
        super(Agent, self).transmit(self.memome, other_node)

    def broadcast(self):
        for vector in self.outgoing_vectors:
            self.transmit(vector.destination)

    def update(self, meme):
        meme.copy_to(self)


class Source(Node):
    __tablename__ = "source"
    __mapper_args__ = {"polymorphic_identity": "source"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    def generate_genome(self):
        raise NotImplementedError

    def generate_memome(self):
        raise NotImplementedError

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

    genome_size = Column(Integer, default=8)
    memome_size = Column(Integer, default=8)

    @staticmethod
    def _binary_string(length):
        return "".join(np.random.randint(0, 2, length).astype(str))

    def generate_genome(self):
        return Genome(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._binary_string(self.genome_size))

    def generate_memome(self):
        return Memome(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._binary_string(self.memome_size))
