from models import Transformation


class Replication(Transformation):

    """The identity transformation."""

    __mapper_args__ = {"polymorphic_identity": "replication"}


class Mutation(Transformation):

    """The mutation transformation."""

    __mapper_args__ = {"polymorphic_identity": "mutation"}


class Observation(Transformation):

    """The observation transformation."""

    __mapper_args__ = {"polymorphic_identity": "observation"}
