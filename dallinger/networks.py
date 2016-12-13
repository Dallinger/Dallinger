"""Network structures commonly used in simulations of evolution."""

from operator import attrgetter
import random

from .models import Network
from .nodes import Source


class Chain(Network):
    """Source -> Node -> Node -> Node -> ...

    The source is optional, but must be added first.
    """

    __mapper_args__ = {"polymorphic_identity": "chain"}

    def add_node(self, node):
        """Add an agent, connecting it to the previous node."""
        other_nodes = [n for n in self.nodes() if n.id != node.id]

        if isinstance(node, Source) and other_nodes:
            raise(Exception("Chain network already has a nodes, "
                            "can't add a source."))

        if other_nodes:
            parent = max(other_nodes, key=attrgetter('creation_time'))
            parent.connect(whom=node)


class FullyConnected(Network):
    """A fully-connected network (complete graph) with all possible vectors."""

    __mapper_args__ = {"polymorphic_identity": "fully-connected"}

    def add_node(self, node):
        """Add a node, connecting it to everyone and back."""
        other_nodes = [n for n in self.nodes() if n.id != node.id]

        for n in other_nodes:
            if isinstance(n, Source):
                node.connect(direction="from", whom=n)
            else:
                node.connect(direction="both", whom=n)


class Empty(Network):
    """An empty network with no vectors."""

    __mapper_args__ = {"polymorphic_identity": "empty"}

    def add_node(self, node):
        """Do nothing."""
        pass

    def add_source(self, source):
        """Connect the source to all existing other nodes."""
        nodes = [n for n in self.nodes() if not isinstance(n, Source)]
        source.connect(whom=nodes)


class Star(Network):
    """A star network.

    A star newtork has a central node with a pair of vectors, incoming and
    outgoing, with all other nodes.
    """

    __mapper_args__ = {"polymorphic_identity": "star"}

    def add_node(self, node):
        """Add a node and connect it to the center."""
        nodes = self.nodes()

        if len(nodes) > 1:
            first_node = min(nodes, key=attrgetter('creation_time'))
            first_node.connect(direction="both", whom=node)


class Burst(Network):
    """A burst network.

    A burst network has a central node with an outgoing connection to each of
    the other nodes.
    """

    __mapper_args__ = {"polymorphic_identity": "burst"}

    def add_node(self, node):
        """Add a node and connect it to the center."""
        nodes = self.nodes()

        if len(nodes) > 1:
            first_node = min(nodes, key=attrgetter('creation_time'))
            first_node.connect(whom=node)


class DiscreteGenerational(Network):
    """A discrete generational network.

    A discrete generational network arranges agents into none-overlapping
    generations. Each agent is connected to all agents in the previous
    generation. If initial_source is true agents in the first generation will
    connect to the oldest source in the network. generation_size dictates how
    many agents are in each generation, generations sets how many generations
    the network involves.

    Note that this network type assumes that agents have a property called
    generation. If you agents do not have this property it will not work.
    """

    __mapper_args__ = {"polymorphic_identity": "discrete-generational"}

    def __init__(self, generations, generation_size, initial_source):
        """Endow the network with some persistent properties."""
        self.property1 = repr(generations)
        self.property2 = repr(generation_size)
        self.property3 = repr(initial_source)
        if self.initial_source:
            self.max_size = repr(generations * generation_size + 1)
        else:
            self.max_size = repr(generations * generation_size)

    @property
    def generations(self):
        """The length of the network: the number of generations."""
        return int(self.property1)

    @property
    def generation_size(self):
        """The width of the network: the size of a single generation."""
        return int(self.property2)

    @property
    def initial_source(self):
        """The source that seeds the first generation."""
        return bool(self.property3)

    def add_node(self, node):
        """Link the agent to a random member of the previous generation."""
        nodes = [n for n in self.nodes() if not isinstance(n, Source)]
        num_agents = len(nodes)
        curr_generation = int((num_agents - 1) / float(self.generation_size))
        node.generation = curr_generation

        if curr_generation == 0:
            if self.initial_source:
                source = min(
                    self.nodes(type=Source),
                    key=attrgetter('creation_time'))
                source.connect(whom=node)
                source.transmit(to_whom=node)
        else:
            prev_agents = type(node).query\
                .filter_by(failed=False,
                           network_id=self.id,
                           generation=(curr_generation - 1))\
                .all()
            prev_fits = [p.fitness for p in prev_agents]
            prev_probs = [(f / (1.0 * sum(prev_fits))) for f in prev_fits]

            rnd = random.random()
            temp = 0.0
            for i, probability in enumerate(prev_probs):
                temp += probability
                if temp > rnd:
                    parent = prev_agents[i]
                    break

            parent.connect(whom=node)
            parent.transmit(to_whom=node)


class ScaleFree(Network):
    """Barabasi-Albert (1999) model of a scale-free network.

    The construction process begins with a fully-connected network with m0
    individuals. After that point, every newcomer makes m connections with
    existing memebers of the network. Critically, new connections are
    chosen using preferential attachment (i.e., you connect with agents
    according to how many connections they already have).
    """

    __mapper_args__ = {"polymorphic_identity": "scale-free"}

    def __init__(self, m0, m):
        """Store m0 in property1 and m in property2."""
        self.property1 = repr(m0)
        self.property2 = repr(m)

    @property
    def m0(self):
        """Number of nodes in the fully-connected core."""
        return int(self.property1)

    @property
    def m(self):
        """Number of connections that a newcomer makes."""
        return int(self.property2)

    def add_node(self, node):
        """Add newcomers one by one, using linear preferential attachment."""
        nodes = self.nodes()

        # Start with a core of m0 fully-connected agents...
        if len(nodes) <= self.m0:
            other_nodes = [n for n in nodes if n.id != node.id]
            for n in other_nodes:
                node.connect(direction="both", whom=n)

        # ...then add newcomers one by one with preferential attachment.
        else:
            for idx_newvector in xrange(self.m):

                these_nodes = [
                    n for n in nodes if (
                        n.id != node.id and
                        not n.is_connected(direction="either", whom=node))]

                outdegrees = [
                    len(n.vectors(direction="outgoing")) for n in these_nodes]

                # Select a member using preferential attachment
                ps = [(d / (1.0 * sum(outdegrees))) for d in outdegrees]
                rnd = random.random() * sum(ps)
                cur = 0.0
                for i, p in enumerate(ps):
                    cur += p
                    if rnd < cur:
                        vector_to = these_nodes[i]

                # Create vector from newcomer to selected member and back
                node.connect(direction="both", whom=vector_to)


class SequentialMicrosociety(Network):
    """A microsociety."""

    __mapper_args__ = {"polymorphic_identity": "microsociety"}

    def __init__(self, n):
        """Store n in property1."""
        self.property1 = repr(n)

    @property
    def n(self):
        """Number of nodes active at once."""
        return int(self.property1)

    def add_node(self, node):
        """Add a node, connecting it to all the active nodes."""
        nodes = sorted(
            self.nodes(),
            key=attrgetter('creation_time'), reverse=True)

        other_nodes = [n for n in nodes if n.id != node.id]

        connecting_nodes = other_nodes[0:(self.n - 1)]

        for n in connecting_nodes:
            n.connect(whom=node)
