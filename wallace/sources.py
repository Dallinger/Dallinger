from .models import Node, Info, Transmission
from sqlalchemy import ForeignKey, Column, String
import random


class Source(Node):
    __tablename__ = "source"
    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    def _selector(self):
        raise NotImplementedError("You need to overwrite the default _selector")

    def create_information(self):
        """Generate new information."""
        raise NotImplementedError("You need to overwrite the default create_information")


class RandomBinaryStringSource(Source):
    """An agent whose genome and memome are random binary strings. The source
    only transmits; it does not update.
    """

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    @staticmethod
    def _data():
        return "".join([str(random.randint(0, 1)) for i in range(2)])
