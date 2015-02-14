from models import Transformation


class Replication(Transformation):

    """The identity transformation."""

    __mapper_args__ = {"polymorphic_identity": "replication"}


class Mutation(Transformation):

    """The identity transformation."""

    __mapper_args__ = {"polymorphic_identity": "mutation"}
