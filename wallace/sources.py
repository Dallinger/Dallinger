from .models import Node, Info
from sqlalchemy import ForeignKey, Column, String, Integer
import random


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
