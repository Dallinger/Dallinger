"""
Define custom transformations.

See class Transformation in models.py for the base class Transformation. This
file stores a list of all the subclasses of Transformation made available by
default. Note that they don't necessarily tell you anything about the nature
in which two Info's relate to each other, but if used sensibly they will do so.
"""

from models import Transformation, Info
import random


class Replication(Transformation):

    """The identity transformation."""

    __mapper_args__ = {"polymorphic_identity": "replication"}


def replicate(node, info_in, info_out=None):
    if info_out is None:
        info_out = type(info_in)(origin=node, contents=info_in.contents)
    Replication(info_in=info_in, info_out=info_out)

    return info_out


class Mutation(Transformation):

    """The mutation transformation."""

    __mapper_args__ = {"polymorphic_identity": "mutation"}


def mutate(info_in, node, alleles=None, info_out=None):
    if info_out is None and (alleles is None or not isinstance(alleles, list)):
        raise ValueError("You need to pass mutate a list of possible alleles")
    if info_out is None:
        current_allele = info_in.contents
        new_allele = random.choice([a for a in alleles if a != current_allele])
        info_out = type(info_in)(origin=node, contents=new_allele)
    Mutation(info_in=info_in, info_out=info_out)


class Shuffle(Transformation):

    __mapper_args__ = {"polymorphic_identity": "shuffle"}


def shuffle(info_in, node, info_out=None):
    if info_out is None:
        contents = info_in.contents
        contents = ''.join(
            random.sample(info_in.contents, len(info_in.contents)))
        info_out = type(info_in)(origin=node, contents=contents)
    Shuffle(info_in=info_in, info_out=info_out)

    return info_out


class Observation(Transformation):

    """The observation transformation."""

    __mapper_args__ = {"polymorphic_identity": "observation"}
