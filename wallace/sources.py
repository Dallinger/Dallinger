from .models import Node, Info, Transmission
from sqlalchemy import ForeignKey, Column, String
import random


class Source(Node):
    __tablename__ = "source"
    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    def _selector(self):
        return []

    def create_information(self):
        """Generate new information."""
        return NotImplementedError

    def transmit(self, other_node, selector=None):

        if selector is None:
            cls = Info

        elif issubclass(selector, Info):
            cls = selector

        info = cls(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._data())

        super(Source, self).transmit(other_node, selector=info)

    def broadcast(self):
        for vector in self.outgoing_vectors:
            self.transmit(vector.destination, selector=Info)


class RandomBinaryStringSource(Source):
    """An agent whose genome and memome are random binary strings. The source
    only transmits; it does not update.
    """

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    @staticmethod
    def _data():
        return "".join([str(random.randint(0, 1)) for i in range(2)])
