from .models import Vector
from .agents import Agent, Source
import numpy as np


class Network(object):
    """A network of agents."""

    def __init__(self, db):
        self.db = db

    @property
    def agents(self):
        return self.db.query(Agent)\
            .order_by(Agent.creation_time)\
            .filter_by(is_visible=True)\
            .all()

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

    def add_local_source(self, source, agent):
        self.db.add(source)
        source.connect_to(agent)
        self.db.commit()

    def trigger_source(self, source):
        source.broadcast()
        self.db.commit()

    def add_node(self, node):
        self.db.add(node)
        self.db.commit()

    def add_agent(self):
        agent = Agent()
        self.db.add(agent)
        self.db.commit()
        return agent

    def __len__(self):
        return len(self.agents)

    def __repr__(self):
        return "<{} with {} agents, {} sources, {} links>".format(
            type(self).__name__,
            len(self.agents),
            len(self.sources),
            len(self.links))


class Chain(Network):
    """A -> B -> C -> ..."""

    def __init__(self, db, size=0):
        super(Chain, self).__init__(db)
        if len(self) == 0:
            for i in xrange(size):
                self.add_agent()

    @property
    def first_agent(self):
        if len(self) > 0:
            return self.db.query(Agent)\
                .order_by(Agent.creation_time)\
                .filter_by(is_visible=True)\
                .first()
        else:
            return None

    @property
    def last_agent(self):
        if len(self) > 0:
            return self.db.query(Agent)\
                .order_by(Agent.creation_time.desc())\
                .filter_by(is_visible=True)\
                .first()
        else:
            return None

    def add_agent(self, newcomer=None):
        if newcomer is None:
            newcomer = Agent()

        if len(self) == 0:
            self.add_node(newcomer)
        else:
            last_agent = self.last_agent
            self.add_node(newcomer)
            last_agent.connect_to(newcomer)
        return newcomer


class FullyConnected(Network):
    """In a fully-connected network (complete graph), all possible links exist.
    """

    def __init__(self, db, size=0):
        super(FullyConnected, self).__init__(db)
        if len(self) == 0:
            for i in xrange(size):
                self.add_agent()

    def add_agent(self, newcomer=None):
        if newcomer is None:
            newcomer = Agent()

        self.db.add(newcomer)

        for agent in self.agents:
            if agent is not newcomer:
                newcomer.connect_to(agent)
                newcomer.connect_from(agent)

        self.db.commit()
        return newcomer


class ScaleFree(Network):
    """Barabasi-Albert (1999) model for constructing a scale-free network. The
    construction process begins with a fully-connected network with m0
    individuals. Each newcomer makes m connections with existing memebers of
    the network. Critically, new connections are chosen using preferential
    attachment.
    """

    def __init__(self, db, size=0, m0=4, m=4):
        super(ScaleFree, self).__init__(db)
        self.db = db
        self.m = m
        self.m0 = m0

        if len(self) == 0:
            for i in xrange(size):
                self.add_agent()

    def add_agent(self, newcomer=None):
        if newcomer is None:
            newcomer = Agent()
        self.db.add(newcomer)
        self.db.commit()

        # Start with a core of m0 fully-connected agents...
        if len(self) <= self.m0:
            for agent in self.agents:
                if agent is not newcomer:
                    newcomer.connect_to(agent)
                    newcomer.connect_from(agent)
            self.db.commit()

        # ...then add newcomers one by one with preferential attachment.
        else:
            for idx_newlink in xrange(self.m):
                these_agents = []
                for agent in self.agents:
                    if (agent == newcomer or
                            agent.has_connection_from(newcomer) or
                            agent.has_connection_to(newcomer)):
                        continue
                    else:
                        these_agents.append(agent)
                d = np.array([a.outdegree for a in these_agents], dtype=float)

                # Select a member using preferential attachment
                p = d / np.sum(d)
                idx_linkto = np.flatnonzero(np.random.multinomial(1, p))[0]
                link_to = these_agents[idx_linkto]

                # Create link from the newcomer to the selected member, and back
                newcomer.connect_to(link_to)
                newcomer.connect_from(link_to)
                self.db.commit()

        return newcomer
