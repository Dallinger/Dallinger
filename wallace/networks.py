"""Network structures commonly used in simulations of evolution."""

from .models import Network, Agent, Source
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


class ScaleFree(Network):

    """Barabasi-Albert (1999) model for constructing a scale-free network.

    The construction process begins with a fully-connected network with m0
    individuals. After that point, every newcomer makes m connections with
    existing memebers of the network. Critically, new connections are
    chosen using preferential attachment (i.e., you connect with agents
    according to how many connections they already have).
    """

    __mapper_args__ = {"polymorphic_identity": "scale-free"}

    def __init__(self, m0=4, m=4):
        self.m = m
        self.m0 = m0

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
                            agent.has_connection_from(newcomer) or
                            agent.has_connection_to(newcomer)):
                        continue
                    else:
                        these_agents.append(agent)
                outdegrees = [a.outdegree for a in these_agents]

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
