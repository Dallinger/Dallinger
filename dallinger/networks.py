"""Network structures commonly used in simulations of evolution."""

import random
from operator import attrgetter

from .models import Network
from .nodes import Agent, Source


class DelayedChain(Network):
    """Source -> Node -> Node -> Node -> ...

    If a Source exists in the network, it will be used as the parent for
    the first 11 Nodes added. Beyond that number, the most recently added
    Node will be assigned as the parent.

    If no Source exists, the first 11 Nodes will have no parent assigned.
    """

    __mapper_args__ = {"polymorphic_identity": "delayed_chain"}

    def add_node(self, node):
        """Add an agent, connecting it to the previous node."""
        other_nodes = [n for n in self.nodes() if n.id != node.id]
        if len(self.nodes()) > 11:
            parents = [max(other_nodes, key=attrgetter("creation_time"))]
        else:
            parents = [n for n in other_nodes if isinstance(n, Source)]

        for parent in parents:
            parent.connect(whom=node)


class Chain(Network):
    """Source -> Node -> Node -> Node -> ...

    The source is optional, but must be added first.
    """

    __mapper_args__ = {"polymorphic_identity": "chain"}

    def add_node(self, node):
        """Add an agent, connecting it to the previous node."""
        other_nodes = [n for n in self.nodes() if n.id != node.id]

        if isinstance(node, Source) and other_nodes:
            raise Exception("Chain network already has a nodes, " "can't add a source.")

        if other_nodes:
            parent = max(other_nodes, key=attrgetter("creation_time"))
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
            first_node = min(nodes, key=attrgetter("creation_time"))
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
            first_node = min(nodes, key=attrgetter("creation_time"))
            first_node.connect(whom=node)


class DiscreteGenerational(Network):
    """A discrete generational network.

    A discrete generational network arranges agents into none-overlapping
    generations.

    If initial_source is true, agents in the first generation will connect to
    the oldest source in the network as their parent. Otherwise, they will be
    parentless. For Agents in subsequent generations, a parent will be
    selected from the previous generation with probability proportional to the
    parent's fitness, with fitter parents more likely to be selected.

    generation_size dictates how many agents are in each generation,
    generations sets how many generations the network involves.

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
            self.max_size = generations * generation_size + 1
        else:
            self.max_size = generations * generation_size

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
        return self.property3.lower() != "false"

    def add_node(self, node):
        """Link to the agent from a parent based on the parent's fitness"""
        num_agents = len(self.nodes(type=Agent))
        curr_generation = int((num_agents - 1) / float(self.generation_size))
        node.generation = curr_generation

        if curr_generation == 0 and self.initial_source:
            parent = self._select_oldest_source()
        else:
            parent = self._select_fit_node_from_generation(
                node_type=type(node), generation=curr_generation - 1
            )

        if parent is not None:
            parent.connect(whom=node)
            parent.transmit(to_whom=node)

    def _select_oldest_source(self):
        return min(self.nodes(type=Source), key=attrgetter("creation_time"))

    def _select_fit_node_from_generation(self, node_type, generation):
        prev_agents = node_type.query.filter_by(
            failed=False, network_id=self.id, generation=(generation)
        ).all()
        prev_fits = [p.fitness for p in prev_agents]
        prev_probs = [(f / (1.0 * sum(prev_fits))) for f in prev_fits]

        rnd = random.random()
        temp = 0.0
        for i, probability in enumerate(prev_probs):
            temp += probability
            if temp > rnd:
                return prev_agents[i]


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
            for idx_newvector in range(self.m):
                these_nodes = [
                    n
                    for n in nodes
                    if (
                        n.id != node.id
                        and not n.is_connected(direction="either", whom=node)
                    )
                ]

                outdegrees = [len(n.vectors(direction="outgoing")) for n in these_nodes]

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
        for predecessor in self._most_recent_predecessors_to(node):
            predecessor.connect(whom=node)

    def _most_recent_predecessors_to(self, node):
        other_nodes = [n for n in self.nodes() if n.id != node.id]

        other_nodes_newest_first = sorted(
            other_nodes, key=attrgetter("creation_time"), reverse=True
        )

        return other_nodes_newest_first[: (self.n - 1)]


class SplitSampleNetwork(Network):
    """
    A network that automatically implements an unpaired split-sample
    experimental design.
    """

    __mapper_args__ = {"polymorphic_identity": "particle_network"}

    def __init__(self):
        self.property1 = random.random() < 0.5

    @property
    def exploratory(self):
        """Is this network part of the exploratory data subset?"""
        return bool(self.property1)
