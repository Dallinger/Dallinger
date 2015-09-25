"""
Define custom transformations.

See class Transformation in models.py for the base class Transformation. This
file stores a list of all the subclasses of Transformation made available by
default. Note that they don't necessarily tell you anything about the nature
in which two Info's relate to each other, but if used sensibly they will do so.
"""

from models import Transformation


class Replication(Transformation):

    """The identity transformation."""

    __mapper_args__ = {"polymorphic_identity": "replication"}


class Mutation(Transformation):

    """The mutation transformation."""

    __mapper_args__ = {"polymorphic_identity": "mutation"}


class Compression(Transformation):

    """The compression transformation."""

    __mapper_args__ = {"polymorphic_identity": "compression"}


class Response(Transformation):

    """The response transformation."""

    __mapper_args__ = {"polymorphic_identity": "response"}
