from .models import Node, Info
from sqlalchemy import ForeignKey, Column, String
import random


class Source(Node):
    __tablename__ = "source"
    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    def create_information(self, what=None, to_whom=None):
        """Generate new information."""
        raise NotImplementedError(
            "You need to overwrite the default create_information.")

    def transmit(self, what=None, to_whom=None):
        self.create_information(what=what, to_whom=to_whom)
        super(Source, self).transmit(to_whom=to_whom, what=what)


class RandomBinaryStringSource(Source):
    """An agent whose genome and memome are random binary strings. The source
    only transmits; it does not update.
    """

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    def create_information(self, what=None, to_whom=None):
        Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._binary_string())

    def _binary_string(self):
        return "".join([str(random.randint(0, 1)) for i in range(2)])
