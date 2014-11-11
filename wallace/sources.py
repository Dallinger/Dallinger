from .models import Node, Info
from sqlalchemy import ForeignKey, Column, String
import random


class Source(Node):
    __tablename__ = "source"
    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    @staticmethod
    def _data():
        return NotImplementedError

    def transmit(self, other_node):
        info = Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._data())

        super(Source, self).transmit(info, other_node)

    def broadcast(self):
        for vector in self.outgoing_vectors:
            self.transmit(vector.destination)


class RandomBinaryStringSource(Source):
    """An agent whose genome and memome are random binary strings. The source
    only transmits; it does not update.
    """

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    @staticmethod
    def _data():
        return "".join([str(random.randint(0, 1)) for i in range(2)])
