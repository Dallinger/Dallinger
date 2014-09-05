from .models import Info


class Genome(Info):
    __mapper_args__ = {"polymorphic_identity": "genome"}


class Memome(Info):
    __mapper_args__ = {"polymorphic_identity": "memome"}
