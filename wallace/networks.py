from .models import Vector
from .agents import Agent, Source
import numpy as np


class Network(object):
    """A network of agents."""

    def __init__(self, db):
        self.db = db

    @property
    def agents(self):
        return self.db.query(Agent).order_by(
            Agent.creation_time).all()

    @property
    def sources(self):
        return self.db.query(Source).order_by(
            Source.creation_time).all()

    @property
    def links(self):
        return self.db.query(Vector).order_by(
            Vector.origin_id, Vector.destination_id).all()

    def get_degrees(self):
        return [agent.outdegree for agent in self.agents]

    def add_global_source(self, source):
        self.db.add(source)
        for agent in self.agents:
            source.connect_to(agent)
        self.db.commit()

    def trigger_source(self, source):
        source.broadcast()
        self.db.commit()

    def __len__(self):
        return len(self.agents)

    def __repr__(self):
        return "\n".join(map(str, self.links))


class Chain(Network):
    """A -> B -> C -> ..."""

    def __init__(self, db, size):
        super(Chain, self).__init__(db)
        for i in xrange(size):
            self.add_agent()

    @property
    def last_agent(self):
        if len(self) > 0:
            return self.db.query(Agent).filter_by(outdegree=0).one()
        return None

    def add_agent(self):
        agent = Agent()
        if len(self) > 0:
            self.last_agent.connect_to(agent)
        self.db.add(agent)
        self.db.commit()


class FullyConnected(Network):
    """In a fully-connected network (complete graph), all possible links exist.
    """

    def __init__(self, db, size):
        super(FullyConnected, self).__init__(db)
        for i in xrange(size):
            self.add_agent()

    def add_agent(self):
        newcomer = Agent()
        for agent in self.agents:
            newcomer.connect_to(agent)
            newcomer.connect_from(agent)
        self.db.add(newcomer)
        self.db.commit()


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
