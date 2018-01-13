"""Define kinds of nodes: agents, sources, and environments."""

# from operator import attrgetter

from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import Boolean, String
from sqlalchemy.sql.expression import cast

# from dallinger.information import State
from dallinger.models import Node, Network, Info, timenow
from dallinger.nodes import Source


class Bystander(Node):
    """Bystander"""

    __mapper_args__= {"polymorphic_identity":"bystander"}

    @hybrid_property
    def fake_name(self):
        """Convert property1 to fake name."""
        try:
            return self.property1
        except TypeError:
            return None

    @fake_name.setter
    def fake_name(self, name):
        """Make name settable."""
        self.property1 = name

    @fake_name.expression
    def fake_name(self):
        """Make name queryable."""
        return self.property1

    @hybrid_property
    def alive(self):
        """Convert property2 to alive."""
        try:
            return self.property2
        except TypeError:
            return None

    @alive.setter
    def alive(self, is_alive):
        """Make alive settable."""
        self.property2 = is_alive

    @alive.expression
    def alive(self):
        """Make alive queryable."""
        return self.property2

class Mafioso(Bystander):
    """Member of the mafia."""

    __mapper_args__= {"polymorphic_identity":"mafioso"}


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
            return self.property1
        except TypeError:
            return None

    @daytime.setter
    def daytime(self, is_daytime):
        """Make time settable."""
        self.property1 = is_daytime

    @daytime.expression
    def daytime(self):
        """Make time queryable."""
        return self.property1

    def fail_bystander_vectors(self):
        # mafiosi = self.nodes(type=Mafioso)
        mafiosi = Node.query.filter_by(network_id=self.id, property2='True', type='mafioso').all()
        for v in self.vectors():
            if not isinstance(v.origin, Source) and not (v.origin in mafiosi and v.destination in mafiosi):
                v.fail()

    def vote(self, nodes):
        votes = {}
        for node in nodes:
            infos = Info.query.filter_by(origin_id=node.id).order_by('creation_time')
            vote = infos[-1].contents.split(': ')[1]
            if vote in votes:
                votes[vote] += 1
            else:
                votes[vote] = 1
        k = list(votes.keys())
        v = list(votes.values())
        victim_name = k[v.index(max(v))]
        victim_node = Node.query.filter_by(property1=victim_name).one()
        victim_node.alive = 'False'
        for v in victim_node.vectors():
            v.fail()
        for i in victim_node.infos():
            i.fail()
        for t in victim_node.transmissions(direction="all"):
            t.fail()
        for t in victim_node.transformations():
            t.fail()
        return victim_name

    def setup_daytime(self):
        # mafiosi = self.nodes(type=Mafioso)
        mafiosi = Node.query.filter_by(network_id=self.id, property2='True', type='mafioso').all()
        victim_name = self.vote(mafiosi)
        self.daytime = 'True'
        # nodes = [n for n in self.nodes() if not isinstance(n, Source)]
        nodes = Node.query.filter_by(network_id=self.id, property2='True').all()
        for n in nodes:
            for m in nodes:
                if n != m:
                    n.connect(whom=m, direction="to")
        return victim_name

    def setup_nighttime(self):
        # nodes = self.nodes()
        nodes = Node.query.filter_by(network_id=self.id, property2='True').all()
        victim_name = self.vote(nodes)
        mafiosi = Node.query.filter_by(network_id=self.id, property2='True', type='mafioso').all()
        winner = None
        if len(mafiosi) >= len(nodes) - 1:
            winner = 'mafia'
            return victim_name, winner
        if len(mafiosi) == 0:
            winner = 'townspeople'
            return victim_name, winner
        self.daytime = 'False'
        self.fail_bystander_vectors()
        return victim_name, winner
