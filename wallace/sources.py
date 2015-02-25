from .models import Node, Info, Source
from sqlalchemy import ForeignKey, Column, String
import random


class RandomBinaryStringSource(Source):
    """An agent whose genome and memome are random binary strings. The source
    only transmits; it does not update.
    """

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    def create_information(self):
        info = Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._binary_string())
        return info

    def _binary_string(self):
        return "".join([str(random.randint(0, 1)) for i in range(2)])

    def _what(self):
        return self.create_information()
