from models import Transformation, Info


class IdentityTransformation(Transformation):
    """The identity transformation."""

    __mapper_args__ = {"polymorphic_identity": "identity_tranformation"}

    def apply(self):
        info_out = Info(
            origin=self.node,
            contents=self.info_in.contents)

        self.info_out = info_out

        return info_out
