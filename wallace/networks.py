from agents import Agent
import numpy as np


class Network(object):
    """A network of agents."""

    def __init__(self, size):
        self.agents = []
        self.sources = []
        self.links = []

    def get_degrees(self):
        counts = np.zeros(len(self))
        for idx_agent in xrange(len(self)):
            counts[idx_agent] = np.sum(
                [1 for link in self.links if link[0] is self.agents[idx_agent]])
        return counts

    def add_global_source(self, source):
        self.sources.append(source)
        for agent in self.agents:
            self.links.append((source, agent))

    def trigger_source(self, source):
        for link in self.links:
            if link[0] is source:
                link[1].update(source.transmit())

    def __len__(self):
        return len(self.agents)

    def __repr__(self):
        return "\n".join(["({}, {})".format(link[0], link[1])
                         for link in self.links])


class Chain(Network):
    """A -> B -> C -> ..."""

    def __init__(self, size):
        self.agents = [Agent(), Agent()]
        self.sources = []
        self.links = [(self.agents[0], self.agents[1])]
        for i in xrange(size - 2):
            self.add_agent(Agent())

    def add_agent(self, agent):
        self.agents.append(agent)
        heads = [link[0] for link in self.links]
        tails = [link[1] for link in self.links]
        final_agent = list(set(tails) - set(heads))
        self.links.append((final_agent[0], agent))


class FullyConnected(Network):
    """In a fully-connected network (complete graph), all possible links exist.
    """

    def __init__(self, size):
        self.agents = [Agent() for i in xrange(size)]
        self.sources = []
        self.links = [(x, y) for x in self.agents for y in self.agents if x != y]

    def add_agent(self):
        newcomer = Agent()
        for agent in self.agents:
            self.links.append((newcomer, agent))
            self.links.append((agent, newcomer))


class ScaleFree(Network):
    """Barabasi-Albert (1999) model for constructing a scale-free network. The
    construction process begins with a fully-connected network with m0
    individuals. Each newcomer makes m connections with existing memebers of
    the network. Critically, new connections are chosen using preferential
    attachment.
    """

    def __init__(self, size, m0=4, m=4):
        core = FullyConnected(m0)
        self.m = m
        self.agents = core.agents
        self.sources = []
        self.links = core.links
        for i in xrange(size - m0):
            self.add_agent()

    def add_agent(self):
        newcomer = Agent()
        self.agents.append(newcomer)
        for idx_newlink in xrange(self.m):
            d = self.get_degrees()
            for idx_agent in xrange(len(self)):
                # Set degree of existing links to zero to prevent repeats
                if (newcomer, self.agents[idx_agent]) in self.links:
                    d[idx_agent] = 0

                if self.agents[idx_agent] is newcomer:
                    d[idx_agent] = 0

            # Select a member using preferential attachment
            p = d/np.sum(d)
            idx_linkto = np.flatnonzero(np.random.multinomial(1, p))[0]
            link_to = self.agents[idx_linkto]

            # Create link from the newcomer to the selected member, and back
            self.links.append((newcomer, link_to))
            self.links.append((link_to, newcomer))
