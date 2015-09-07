"""Network structures commonly used in simulations of evolution."""

from .models import Network
from .nodes import Agent, Source
from sqlalchemy import and_
import random


class Chain(Network):

    """
    Source -> Agent -> Agent -> Agent -> ...

    The source is optional and can be added at any time
    """

    __mapper_args__ = {"polymorphic_identity": "chain"}

    def add_agent(self, newcomer):
        """Add an agent, connecting it to the previous node."""
        agents = self.nodes(type=Agent)
        other_agents = [a for a in agents if a.uuid != newcomer.uuid]

        sources = self.nodes(type=Source)

        from operator import attrgetter
        if other_agents:
            max(other_agents, key=attrgetter('creation_time')).connect(whom=newcomer)
        elif sources:
            min(sources, key=attrgetter('creation_time')).connect(whom=newcomer)

    def add_source(self, source):
        if len(self.nodes(type=Source)) > 1:
            raise(Exception("Cannot add another source to Chain network as it already has a source"))
        else:
            if len(self.nodes(type=Agent)) > 0:
                from operator import attrgetter
                source.connect(whom=min(self.nodes(type=Agent), key=attrgetter('creation_time')))

    def calculate_full(self):
        self.full = len(self.nodes(type=Agent)) >= self.max_size


class FullyConnected(Network):

    """A fully-connected network (complete graph) with all possible vectors."""

    __mapper_args__ = {"polymorphic_identity": "fully-connected"}

    def add_agent(self, newcomer):
        """Add an agent, connecting it to everyone and back."""
        agents = self.nodes(type=Agent)

        if len(agents) > 1:
            other_agents = [a for a in agents if a.uuid != newcomer.uuid]
            for agent in other_agents:
                agent.connect(direction="both", whom=newcomer)

    def calculate_full(self):
        self.full = len(self.nodes(type=Agent)) >= self.max_size


class Empty(Network):

    """An empty network with no vectors."""

    __mapper_args__ = {"polymorphic_identity": "empty"}

    def add_agent(self, newcomer):
        """Add an agent, connecting it to everyone and back."""
        pass

    def calculate_full(self):
        """Determine whether the network is full by counting the agents."""
        self.full = len(self.nodes(type=Agent)) >= self.max_size

    def add_source(self, source):
        """Connect the source to all existing agents."""
        agents = self.nodes(type=Agent)
        for agent in agents:
            source.connect(whom=agent)


class Star(Network):

    """A star network.

    A star newtork has a central node with a pair of vectors, incoming and
    outgoing, with all other nodes.
    """

    __mapper_args__ = {"polymorphic_identity": "star"}

    def add_agent(self, newcomer):
        """Add an agent and connect it to the center."""

        agents = self.nodes(type=Agent)

        if len(agents) > 1:
            from operator import attrgetter
            first_agent = min(agents, key=attrgetter('creation_time'))
            first_agent.connect(direction="both", whom=newcomer)


class Burst(Network):

    """A burst network.

    A burst network has a central node with an outgoing connection to each of
    the other nodes.
    """

    __mapper_args__ = {"polymorphic_identity": "burst"}

    def add_agent(self, newcomer):
        """Add an agent and connect it to the center."""
        agents = self.nodes(type=Agent)

        if len(agents) > 1:
            from operator import attrgetter
            first_agent = min(agents, key=attrgetter('creation_time'))
            first_agent.connect(whom=newcomer)


class DiscreteGenerational(Network):

    """A discrete generational network.

    A discrete generational network arranges agents into none-overlapping
    generations. Each agent is connected to all agents in the previous
    generation. If initial_source is true agents in the first generation will
    connect to the first source. generation_size dictates how many agents are
    in each generation, generations sets how many generations the networks
    involves.
    """

    __mapper_args__ = {"polymorphic_identity": "discrete-generational"}

    def __init__(self, generations, generation_size, initial_source):
        self.property1 = repr(generations)
        self.property2 = repr(generation_size)
        self.property3 = repr(initial_source)
        self.max_size = repr(generations*generation_size)

    @property
    def generations(self):
        return int(self.property1)

    @property
    def generation_size(self):
        return int(self.property2)

    @property
    def initial_source(self):
        return bool(self.property3)

    def add_agent(self, newcomer):
        current_generation = newcomer.generation
        if current_generation == 0:
            if self.initial_source:
                newcomer.connect(direction="from", whom=self.nodes(type=Source)[0])
        else:
            agent_type = type(newcomer)
            prev_agents = agent_type.query\
                .filter(and_(agent_type.failed == False,
                             agent_type.network_uuid == self.uuid,
                             agent_type.generation == current_generation-1))\
                .all()
            prev_fitnesses = [p.fitness for p in prev_agents]
            prev_probs = [(f/(1.0*sum(prev_fitnesses))) for f in prev_fitnesses]

            rnd = random.random()
            temp = 0.0
            for i, probability in enumerate(prev_probs):
                temp += probability
                if temp > rnd:
                    parent = prev_agents[i]
                    break

            parent.connect(direction="to", whom=newcomer)
            parent.transmit(to_whom=newcomer)

    def calculate_full(self):
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
        self.property1 = repr(m0)
        self.property2 = repr(m)

    @property
    def m0(self):
        return int(self.property1)

    @property
    def m(self):
        return int(self.property2)

    def add_agent(self, newcomer):
        """Add newcomers one by one, using linear preferential attachment."""

        agents = self.nodes(type=Agent)

        # Start with a core of m0 fully-connected agents...
        if len(agents) <= self.m0:
            other_agents = [a for a in agents if a.uuid != newcomer.uuid]
            for agent in other_agents:
                newcomer.connect(direction="both", whom=agent)

        # ...then add newcomers one by one with preferential attachment.
        else:
            for idx_newvector in xrange(self.m):
                these_agents = [a for a in agents if a.uuid != newcomer.uuid and not a.is_connected(direction="either", whom=newcomer)]
                # these_agents = []
                # for agent in agents:
                #     if (agent == newcomer or
                #             agent.is_connected(direction="from", whom=newcomer) or
                #             agent.is_connected(direction="to", whom=newcomer)):
                #         continue
                #     else:
                #         these_agents.append(agent)
                outdegrees = [len(a.vectors(direction="outgoing")) for a in these_agents]

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
