from .models import Network
import random


class Chain(Network):
    """A -> B -> C -> ..."""

    __mapper_args__ = {"polymorphic_identity": "chain"}

    def add_agent(self, newcomer):

        newcomer.network = self

        vectors = []
        if len(self.nodes) > 1:
            vector = self.nodes[-2].connect_to(newcomer)
            vectors.append(vector)

        for vector in vectors:
            vector.network = self

        return vectors


class FullyConnected(Network):
    """In a fully-connected network (complete graph), all possible vectors exist.
    """

    __mapper_args__ = {"polymorphic_identity": "fully-connected"}

    def add_agent(self, newcomer):
        vectors = []
        for agent in self.agents:
            if agent is not newcomer:
                vectors.append(agent.connect_to(newcomer))
                vectors.append(agent.connect_from(newcomer))

        newcomer.network = self

        for vector in vectors:
            vector.network = self

        return vectors


class ScaleFree(Network):
    """Barabasi-Albert (1999) model for constructing a scale-free network. The
    construction process begins with a fully-connected network with m0
    individuals. Each newcomer makes m connections with existing memebers of
    the network. Critically, new connections are chosen using preferential
    attachment.
    """

    __mapper_args__ = {"polymorphic_identity": "scale-free"}

    def __init__(self, m0=4, m=4):
        self.m = m
        self.m0 = m0

    def add_agent(self, newcomer):

        vectors = []

        # Start with a core of m0 fully-connected agents...
        if len(self.agents) <= self.m0:
            for agent in self.agents:
                if agent is not newcomer:
                    vectors.append(newcomer.connect_to(agent))
                    vectors.append(newcomer.connect_from(agent))

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
                vectors.append(newcomer.connect_to(vector_to))
                vectors.append(newcomer.connect_from(vector_to))

        newcomer.network = self

        for vector in vectors:
            vector.network = self

        return vectors
