from agents import Agent


class Network(object):
    """A network of agents."""

    def __init__(self, size):
        self.agents = []
        self.sources = []
        self.links = []

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
