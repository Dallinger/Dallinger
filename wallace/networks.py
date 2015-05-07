"""Network structures commonly used in simulations of evolution."""

from .models import Network, Agent, Source
from sqlalchemy import Column, Integer, Boolean, String
from sqlalchemy import ForeignKey
import random


class Chain(Network):

    """
    Source -> Agent -> Agent -> Agent -> ...
    The source is optional and can be added at any time
    """

    __mapper_args__ = {"polymorphic_identity": "chain"}

    def add_agent(self, newcomer):
        """Add an agent, connecting it to the previous node."""
        self.add(newcomer)

        if len(self.nodes(type=Agent)) > 1:
            self.nodes(type=Agent)[-2].connect_to(newcomer)
        elif len(self.nodes(type=Source)) > 0:
            self.nodes(type=Source)[0].connect_to(newcomer)

    def add_source(self, source):
        if len(self.nodes(type=Source)) > 0:
            raise(Exception("Cannot add another source to Chain network as it already has a source"))
        else:
            self.add(source)
            if len(self.nodes(type=Agent)) > 0:
                source.connect_to(self.nodes(type=Agent)[0])


class FullyConnected(Network):

    """
    A fully-connected network (complete graph) with all possible vectors.
    i.e., everyone connects to everyone else
    """

    __mapper_args__ = {"polymorphic_identity": "fully-connected"}

    def add_agent(self, newcomer):
        """Add an agent, connecting it to everyone and back."""
        self.add(newcomer)

        for agent in self.nodes(type=Agent)[:-1]:
            agent.connect_to(newcomer)
            newcomer.connect_to(agent)


class Star(Network):

    """
    A star network has a central node, with a pair of vectors, incoming and
    outgoing, with all other nodes.
    """

    __mapper_args__ = {"polymorphic_identity": "star"}

    def add_agent(self, newcomer):
        """Add an agent and connect it to the center."""
        self.add(newcomer)

        if len(self.nodes(type=Agent)) > 1:
            center = self.nodes(type=Agent)[0]
            center.connect_to(newcomer)
            newcomer.connect_to(center)


class Burst(Network):

    """
    A burst network has a central node with an outgoing connection to all the
    other nodes.
    """

    __mapper_args__ = {"polymorphic_identity": "burst"}

    def add_agent(self, newcomer):
        """Add an agent and connect it to the center."""
        self.add(newcomer)

        if len(self.nodes(type=Agent)) > 1:
            self.nodes(type=Agent)[0].connect_to(newcomer)


class DiscreteGenerational(Network):

    """
    A discrete generational network arranges agents into none-overlapping generations.
    Each agent is connected to all agents in the previous generation.
    If initial_source is true agents in the first generation will connect to the first source.
    generation_size dictates how many agents are in each generation, generations sets
    how many generations the networks involves.
    """

    __mapper_args__ = {"polymorphic_identity": "discrete-generational"}

    def __init__(self, generations, generation_size, initial_source):
        self.property1 = generations
        self.property2 = generation_size
        self.property3 = initial_source
        self.max_size = self.generations*self.generation_size

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
        num_agents = len(self.nodes(type=Agent))
        if num_agents <= self.generation_size and self.initial_source:
            newcomer.connect_from(self.nodes(type=Source)[0])
        else:
            current_generation = int((num_agents-1)/float(self.generation_size))
            newcomer.connect_from(self.agents_of_generation(current_generation-1))

    def agents_of_generation(self, generation):
        first_index = generation*self.generation_size
        last_index = first_index+(self.generation_size)
        return self.nodes(type=Agent)[first_index:last_index]


class ScaleFree(Network):

    """
    Barabasi-Albert (1999) model for constructing a scale-free network.

    The construction process begins with a fully-connected network with m0
    individuals. After that point, every newcomer makes m connections with
    existing memebers of the network. Critically, new connections are
    chosen using preferential attachment (i.e., you connect with agents
    according to how many connections they already have).
    """

    __mapper_args__ = {"polymorphic_identity": "scale-free"}

    def __init__(self, m0, m):
        self.property1 = m0
        self.property2 = m

    @property
    def m0(self):
        return int(self.property1)

    @property
    def m(self):
        return int(self.property2)

    def add_agent(self, newcomer):
        """Add newcomers one by one, using linear preferential attachment."""
        self.add(newcomer)

        # Start with a core of m0 fully-connected agents...
        if len(self.nodes(type=Agent)) <= self.m0:
            for agent in self.nodes(type=Agent)[:-1]:
                newcomer.connect_to(agent)
                agent.connect_to(newcomer)

        # ...then add newcomers one by one with preferential attachment.
        else:
            for idx_newvector in xrange(self.m):
                these_agents = []
                for agent in self.nodes(type=Agent):
                    if (agent == newcomer or
                            agent.is_connected(direction="from", other_node=newcomer) or
                            agent.is_connected(direction="to", other_node=newcomer)):
                        continue
                    else:
                        these_agents.append(agent)
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
                newcomer.connect_to(vector_to)
                newcomer.connect_from(vector_to)
