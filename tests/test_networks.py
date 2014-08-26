from wallace import networks, agents, db
import time


class TestNetworks(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def test_create_network(self):
        net = networks.Network(self.db)
        assert net.db == self.db

    def test_network_agents(self):
        net = networks.Network(self.db)
        assert len(net.agents) == 0

        agent = agents.Agent()
        self.db.add(agent)
        self.db.commit()

        assert net.agents == [agent]

    def test_network_sources(self):
        net = networks.Network(self.db)
        assert len(net.sources) == 0

        source = agents.Source()
        self.db.add(source)
        self.db.commit()

        assert net.sources == [source]

    def test_network_links(self):
        net = networks.Network(self.db)
        assert len(net.links) == 0

        agent1 = agents.Agent()
        agent2 = agents.Agent()
        agent1.connect_to(agent2)
        self.db.add_all([agent1, agent2])
        self.db.commit()

        assert len(net.links) == 1
        assert net.links[0].origin == agent1
        assert net.links[0].destination == agent2

    def test_network_get_degrees(self):
        net = networks.Network(self.db)
        agent1 = agents.Agent()
        self.db.add(agent1)
        self.db.commit()

        time.sleep(1)
        agent2 = agents.Agent()
        self.db.add(agent2)
        self.db.commit()

        assert net.get_degrees() == [0, 0]

        agent1.connect_to(agent2)
        self.db.commit()

        assert net.get_degrees() == [1, 0]

    def test_network_add_global_source(self):
        net = networks.Network(self.db)
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])
        self.db.commit()

        source = agents.RandomBinaryStringSource()
        net.add_global_source(source)

        assert len(net.links) == 2
        assert net.get_degrees() == [0, 0]
        assert net.sources[0].outdegree == 2

    def test_network_trigger_source(self):
        net = networks.Network(self.db)
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])
        self.db.commit()

        source = agents.RandomBinaryStringSource()
        net.add_global_source(source)

        assert agent1.genome is None
        assert agent2.genome is None
        assert agent1.mimeme is None
        assert agent2.mimeme is None

        net.trigger_source(source)

        assert agent1.genome
        assert agent2.genome
        assert agent1.mimeme
        assert agent2.mimeme

    def test_create_chain(self):
        net = networks.Chain(self.db, 4)
        assert len(net) == 4
        assert len(net.links) == 3

    def test_empty_chain_last_agent(self):
        net = networks.Chain(self.db, 0)
        assert net.last_agent is None

    def test_chain_last_agent(self):
        net = networks.Chain(self.db, 4)
        assert net.last_agent is not None
        assert net.last_agent.indegree == 1
        assert net.last_agent.outdegree == 0

    def test_create_fully_connected(self):
        net = networks.FullyConnected(self.db, 4)
        assert len(net) == 4
        assert len(net.links) == 12
        assert net.get_degrees() == [3, 3, 3, 3]
