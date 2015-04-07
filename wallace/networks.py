"""Network structures commonly used in simulations of evolution."""

from .models import Network
import random


class Chain(Network):

    """A -> B -> C -> ..."""

    __mapper_args__ = {"polymorphic_identity": "chain"}

    def add_agent(self, newcomer):
        """Add an agent, connecting it to the previous node."""
        newcomer.network = self

        if len(self.nodes) > 1:
            self.nodes[-2].connect_to(newcomer)


class FullyConnected(Network):

    """A fully-connected network (complete graph) with all possible vectors."""

    __mapper_args__ = {"polymorphic_identity": "fully-connected"}

    def add_agent(self, newcomer):
        """Add an agent, connecting it to everyone and back."""
        newcomer.network = self

        for agent in self.agents:
            if agent is not newcomer:
                agent.connect_to(newcomer)
                agent.connect_from(newcomer)


class ScaleFree(Network):

    """Barabasi-Albert (1999) model for constructing a scale-free network.

    The construction process begins with a fully-connected network with m0
    individuals. Each newcomer makes m connections with existing memebers of
    the network. Critically, new connections are chosen using preferential
    attachment.
    """

    __mapper_args__ = {"polymorphic_identity": "scale-free"}

    def __init__(self, m0=4, m=4):
        self.m = m
        self.m0 = m0

    def add_agent(self, newcomer):
        """Add newcomers one by one, using linear preferential attachment."""
        newcomer.network = self

        # Start with a core of m0 fully-connected agents...
        if len(self.agents) <= self.m0:
            for agent in self.agents:
                if agent is not newcomer:
                    newcomer.connect_to(agent)
                    newcomer.connect_from(agent)

        # ...then add newcomers one by one with preferential attachment.
        else:
            for idx_newvector in xrange(self.m):
                these_agents = []
                for agent in self.agents:
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
