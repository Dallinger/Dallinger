"""Subclasses of information."""

from .models import Info


class Gene(Info):
    """A gene."""

    __mapper_args__ = {
        "polymorphic_identity": "gene"
    }


class Meme(Info):
    """A meme."""

    __mapper_args__ = {
        "polymorphic_identity": "meme"
    }


class State(Info):
    """A state."""

    __mapper_args__ = {
        "polymorphic_identity": "state"
    }
