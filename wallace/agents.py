from sqlalchemy import ForeignKey, Column, String, Integer
from sqlalchemy.orm import relationship

from .models import Node
from .memes import Genome, Mimeme

import numpy as np


class Agent(Node):
    """Agents have genomes and mimemes, and update their contents when faced.
    By default, agents transmit unadulterated copies of their genomes and
    mimemes, with no error or mutation.
    """

    __tablename__ = "agent"
    __mapper_args__ = {"polymorphic_identity": "agent"}

    id = Column(String(32), ForeignKey("node.id"), primary_key=True)

    genome_id = Column(String(32), ForeignKey('meme.id'))
    genome = relationship(Genome, foreign_keys=[genome_id])

    mimeme_id = Column(String(32), ForeignKey('meme.id'))
    mimeme = relationship(Mimeme, foreign_keys=[mimeme_id])

    def transmit(self, other_node):
        super(Agent, self).transmit(self.genome, other_node)
        super(Agent, self).transmit(self.mimeme, other_node)

    def broadcast(self):
        for vector in self.outgoing_vectors:
            self.transmit(vector.destination)

    def update(self, meme):
        if meme.type == "genome":
            self.genome = meme.duplicate()
        elif meme.type == "mimeme":
            self.mimeme = meme.duplicate()
        else:
            raise ValueError("Unhandled meme type: {}".format(meme.type))


class Source(Node):
    __tablename__ = "source"
    __mapper_args__ = {"polymorphic_identity": "source"}

    id = Column(String(32), ForeignKey("node.id"), primary_key=True)

    def generate_genome(self):
        raise NotImplementedError

    def generate_mimeme(self):
        raise NotImplementedError

    def transmit(self, other_node):
        genome = self.generate_genome()
        super(Source, self).transmit(genome, other_node)

        mimeme = self.generate_mimeme()
        super(Source, self).transmit(mimeme, other_node)

    def broadcast(self):
        for vector in self.outgoing_vectors:
            self.transmit(vector.destination)


class RandomBinaryStringSource(Source):
    """An agent whose genome and mimeme are random binary strings. The source
    only transmits; it does not update.
    """

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    genome_size = Column(Integer, default=8)
    mimeme_size = Column(Integer, default=8)

    @staticmethod
    def _binary_string(length):
        return "".join(np.random.randint(0, 2, length).astype(str))

    def generate_genome(self):
        return Genome(contents=self._binary_string(self.genome_size))

    def generate_mimeme(self):
        return Mimeme(contents=self._binary_string(self.mimeme_size))
