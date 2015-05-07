"""Define custom sources."""

from .models import Source
import random


class RandomBinaryStringSource(Source):

    """A source that transmits random binary strings."""

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    def _contents(self):
        return "".join([str(random.randint(0, 1)) for i in range(2)])
