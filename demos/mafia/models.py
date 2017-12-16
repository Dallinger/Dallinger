"""Define kinds of nodes: agents, sources, and environments."""

from operator import attrgetter
import random

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Float
from sqlalchemy.sql.expression import cast

from dallinger.information import State
from dallinger.models import Info
from dallinger.models import Node

class Mafioso(Node):
    """Member of the mafia."""

    __mapper_args__= {"polymorphic_identity":"mafioso"}

class Bystander(Node):
    """Bystander"""

    __mapper_args__= {"polymorphic_identity":"bystander"}

# class MafiaNetwork(Network):

#     @hybrid_property
#     def daytime(self):
#         """Convert property1 to genertion."""
#         return self.property1

#     @daytime.setter
#     def daytime(self, is_daytime):
#         """Make time settable."""
#         self.property1 = repr(is_daytime)

#     @daytime.expression
#     def daytime(self):
#         """Make time queryable."""
#         return cast(self.property1, bool)

#     def fail_all_vectors(self):
#         for v in self.vectors():
#             v.fail()

#     def setup_daytime(self):
#         nodes = self.nodes()
#         for n in nodes:
#             for m in nodes:
#                 if n != m:
#                     n.connect(whom=m, direction="to")

#     def setup_nighttime(self):
#         mafiosi = self.nodes(type=Mafioso)
#         for n in mafiosi:
#             for m in mafiosi:
#                 if n != m:
#                     n.connect(whom=m, direction="to")
