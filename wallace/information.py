from .models import Info


class Gene(Info):
    __mapper_args__ = {"polymorphic_identity": "gene"}


class Meme(Info):
    __mapper_args__ = {"polymorphic_identity": "meme"}
