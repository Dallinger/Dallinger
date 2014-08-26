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
            Vector.origin_uuid, Vector.destination_uuid).all()

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
        self.db.add(newcomer)

        for agent in self.agents:
            if agent == newcomer:
                continue
            newcomer.connect_to(agent)
            newcomer.connect_from(agent)

        self.db.commit()


class ScaleFree(Network):
    """Barabasi-Albert (1999) model for constructing a scale-free network. The
    construction process begins with a fully-connected network with m0
    individuals. Each newcomer makes m connections with existing memebers of
    the network. Critically, new connections are chosen using preferential
    attachment.
    """

    def __init__(self, db, size, m0=4, m=4):
        FullyConnected(db, m0)

        self.db = db
        self.m = m

        for i in xrange(size - m0):
            self.add_agent()

    def add_agent(self):
        newcomer = Agent()
        self.db.add(newcomer)

        for idx_newlink in xrange(self.m):
            agents = []
            for agent in self.agents:
                if agent == newcomer:
                    continue
                if agent.has_connection_from(newcomer):
                    continue
                if agent.has_connection_to(newcomer):
                    continue
                agents.append(agent)
            d = np.array([a.outdegree for a in agents], dtype=float)

            # Select a member using preferential attachment
            p = d / np.sum(d)
            idx_linkto = np.flatnonzero(np.random.multinomial(1, p))[0]
            link_to = agents[idx_linkto]

            # Create link from the newcomer to the selected member, and back
            newcomer.connect_to(link_to)
            newcomer.connect_from(link_to)
            self.db.commit()
