from models import Transformation


class IdentityTransformation(Transformation):

    """The identity transformation."""

    __mapper_args__ = {"polymorphic_identity": "identity_tranformation"}
