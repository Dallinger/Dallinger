"""Define kinds of nodes: agents, sources, and environments."""

# from operator import attrgetter
# import random

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Boolean
from sqlalchemy.sql.expression import cast

# from dallinger.information import State
# from dallinger.models import Info
from dallinger.models import Node, Network
from dallinger.nodes import Source

class Mafioso(Node):
    """Member of the mafia."""

    __mapper_args__= {"polymorphic_identity":"mafioso"}

class Bystander(Node):
    """Bystander"""

    __mapper_args__= {"polymorphic_identity":"bystander"}


class MafiaNetwork(Network):
    """A mafia network that switches between FullyConnected for all and only mafia nodes."""

    __mapper_args__ = {"polymorphic_identity": "mafia-network"}

    def add_node(self, node):
        """Add a node, connecting it to other mafia if mafioso."""
        if node.type == "mafioso":
            other_mafiosi = [n for n in Node.query.filter_by(type="mafioso") if n.id != node.id]
            for n in other_mafiosi:
                node.connect(direction="both", whom=n)

    def add_source(self, source):
        """Connect the source to all existing other nodes."""
        nodes = [n for n in self.nodes() if not isinstance(n, Source)]
        source.connect(whom=nodes)

    @hybrid_property
    def daytime(self):
        """Convert property1 to daytime."""
        try:
            return bool(self.property1)
        except TypeError:
            return None

    @daytime.setter
    def daytime(self, is_daytime):
        """Make time settable."""
        self.property1 = repr(is_daytime)

    @daytime.expression
    def daytime(self):
        """Make time queryable."""
        return cast(self.property1, Boolean)

    # @hybrid_property
    # def votetime(self):
    #     """Convert property2 to votetime."""
    #     try:
    #         return bool(self.property2)
    #     except TypeError:
    #         return None
    #
    # @votetime.setter
    # def votetime(self, is_votetime):
    #     """Make time settable."""
    #     self.property2 = repr(is_votetime)
    #
    # @votetime.expression
    # def votetime(self):
    #     """Make time queryable."""
    #     return cast(self.property2, Boolean)

    def fail_bystander_vectors(self):
        mafiosi = self.nodes(type=Mafioso)
        for v in self.vectors():
            if not isinstance(v.origin, Source) and not (v.origin in mafiosi and v.destination in mafiosi):
                v.fail()

    def setup_daytime(self):
        self.daytime = True
        nodes = [n for n in self.nodes() if not isinstance(n, Source)]
        for n in nodes:
            for m in nodes:
                if n != m:
                    n.connect(whom=m, direction="to")

    def setup_nighttime(self):
        self.daytime = False
        self.fail_bystander_vectors()

    # def setup_votetime(self):
    #     self.votetime = True
    #     source = self.nodes(type=Source)[0]
    #     nodes = [n for n in self.nodes() if not isinstance(n, Source)]
    #     for n in nodes:
    #         source.trasmit(what=nodes, to_whom=n,)
