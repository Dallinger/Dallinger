"""Network structures commonly used in simulations of evolution."""

from .models import Network
from .nodes import Agent, Source
import random
from operator import attrgetter


class Chain(Network):
    """Source -> Node -> Node -> Node -> ...

    The source is optional, but must be added first.
    """

    __mapper_args__ = {"polymorphic_identity": "chain"}

    def add_node(self, node, transmit=True):
        """Add an agent, connecting it to the previous node."""
        other_nodes = [n for n in self.nodes() if n.id != node.id]

        if isinstance(node, Source) and other_nodes:
            raise(Exception("Chain network already has a nodes, "
                            "can't add a source."))

        if other_nodes:
            parent = max(other_nodes,
                         key=attrgetter('creation_time'))
            parent.connect(whom=node)
            if transmit:
                parent.transmit()


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

    def add_node(self, newcomer):
        """Add an agent, connecting it to everyone and back."""
        pass

    def add_source(self, source):
        """Connect the source to all existing agents."""
        agents = self.nodes(type=Agent)
        for agent in agents:
            source.connect(whom=agent)

    def calculate_full(self):
        """Determine whether the network is full by counting the agents."""
        self.full = len(self.nodes(type=Agent)) >= self.max_size


class Star(Network):
    """A star network.

    A star newtork has a central node with a pair of vectors, incoming and
    outgoing, with all other nodes.
    """

    __mapper_args__ = {"polymorphic_identity": "star"}

    def add_node(self, newcomer):
        """Add an agent and connect it to the center."""
        agents = self.nodes(type=Agent)

        if len(agents) > 1:
            first_agent = min(agents, key=attrgetter('creation_time'))
            first_agent.connect(direction="both", whom=newcomer)


class Burst(Network):
    """A burst network.

    A burst network has a central node with an outgoing connection to each of
    the other nodes.
    """

    __mapper_args__ = {"polymorphic_identity": "burst"}

    def add_node(self, newcomer):
        """Add an agent and connect it to the center."""
        agents = self.nodes(type=Agent)

        if len(agents) > 1:
            first_agent = min(agents, key=attrgetter('creation_time'))
            first_agent.connect(whom=newcomer)


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

    def add_node(self, newcomer):
        """Link the agent to a random member of the previous generation."""
        agents = self.nodes(type=Agent)
        num_agents = len(agents)
        curr_generation = int((num_agents - 1) / float(self.generation_size))
        newcomer.generation = curr_generation

        if curr_generation == 0:
            if self.initial_source:
                source = min(
                    self.nodes(type=Source),
                    key=attrgetter('creation_time'))
                source.connect(whom=newcomer)
                source.transmit(to_whom=newcomer)
        else:
            prev_agents = type(newcomer).query\
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

            parent.connect(whom=newcomer)
            parent.transmit(to_whom=newcomer)

    def calculate_full(self):
        """Determine whether the network is full by counting the agents."""
        self.full = len(self.nodes(type=Agent)) >= self.max_size


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

    def add_node(self, newcomer):
        """Add newcomers one by one, using linear preferential attachment."""
        agents = self.nodes(type=Agent)

        # Start with a core of m0 fully-connected agents...
        if len(agents) <= self.m0:
            other_agents = [a for a in agents if a.id != newcomer.id]
            for agent in other_agents:
                newcomer.connect(direction="both", whom=agent)

        # ...then add newcomers one by one with preferential attachment.
        else:
            for idx_newvector in xrange(self.m):

                these_agents = [
                    a for a in agents if (
                        a.id != newcomer.id and
                        not a.is_connected(direction="either", whom=newcomer))]

                outdegrees = [
                    len(a.vectors(direction="outgoing")) for a in these_agents]

                # Select a member using preferential attachment
                ps = [(d / (1.0 * sum(outdegrees))) for d in outdegrees]
                rnd = random.random() * sum(ps)
                cur = 0.0
                for i, p in enumerate(ps):
                    cur += p
                    if rnd < cur:
                        vector_to = these_agents[i]

                # Create vector from newcomer to selected member and back
                newcomer.connect(direction="both", whom=vector_to)


class SequentialMicrosociety(Network):
    """A microsociety."""

    __mapper_args__ = {"polymorphic_identity": "microsociety"}

    def __init__(self, n):
        """Store n in property1."""
        self.property1 = repr(n)

    @property
    def n(self):
        """Number of people active at once."""
        return int(self.property1)

    def add_node(self, newcomer):
        """Add an agent, connecting it to all the active nodes."""
        agents = sorted(
            self.nodes(type=Agent),
            key=attrgetter('creation_time'), reverse=True)

        other_agents = [a for a in agents if a.id != newcomer.id]

        # If the newcomer is one of the first agents, connect from source...
        if len(self.nodes(type=Agent)) < self.n:
            sources = self.nodes(type=Source)
            sources[0].connect(direction="to", whom=newcomer)

        # ... otherwise connect from the previous n - 1 agents.
        else:
            for agent in other_agents[0:(self.n - 1)]:
                agent.connect(direction="to", whom=newcomer)

    def calculate_full(self):
        """Determine whether the network is full by counting the agents."""
        self.full = len(self.nodes(type=Agent)) >= self.max_size
