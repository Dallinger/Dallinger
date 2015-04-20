from wallace import networks, agents, db, sources, models
from nose.tools import assert_raises


class TestNetworks(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def test_create_network(self):
        net = models.Network()
        assert isinstance(net, models.Network)

    def test_network_agents(self):
        net = networks.Network()
        assert len(net.agents) == 0

        agent = agents.Agent()
        self.db.add(agent)

        net.add_agent(agent)

        assert net.agents == [agent]
        assert isinstance(net, models.Network)

    def test_network_sources(self):
        net = networks.Network()

        assert len(net.sources) == 0

        source = sources.Source()
        net.add(source)
        self.db.add(source)

        assert net.sources == [source]

    def test_network_get_nodes(self):
        net = models.Network()

        node1 = models.Node()
        node2 = models.Node()
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        agent3 = agents.Agent()

        net.add([node1, node2, agent1, agent2, agent3])
        self.db.add_all([node1, node2, agent1, agent2, agent3])

        assert net.get_nodes() == [node1, node2, agent1, agent2, agent3]
        assert net.get_nodes(type=agents.Agent) == [agent1, agent2, agent3]

        node1.kill()
        agent1.fail()

        assert net.get_nodes() == [node2, agent2, agent3]
        assert net.get_nodes(status="all") == [node1, node2, agent1, agent2, agent3]
        assert net.get_nodes(status="dead") == [node1]
        assert net.get_nodes(type=agents.Agent, status="all") == [agent1, agent2, agent3]

    def test_network_vectors(self):
        net = networks.Network()

        assert len(net.vectors) == 0

        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])

        net.add_agent(agent1)
        net.add_agent(agent2)
        agent1.connect_to(agent2)

        assert len(net.vectors) == 1
        assert net.vectors[0].origin == agent1
        assert net.vectors[0].destination == agent2

    def test_network_get_degrees(self):
        net = networks.Network()

        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])
        net.add(agent1)
        net.add(agent2)

        assert net.degrees == [0, 0]

        agent1.connect_to(agent2)

        assert net.degrees == [1, 0]

    def test_network_add_source_global(self):
        net = networks.Network()

        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])

        # Add agents to network.
        net.add_agent(agent1)
        net.add_agent(agent2)

        source = sources.RandomBinaryStringSource()
        self.db.add(source)
        net.add(source)
        source.connect_to(net.agents)

        assert len(net.vectors) == 2
        assert source.network == net
        assert agent1.network == net
        assert net.degrees == [0, 0]
        assert net.sources[0].outdegree == 2

    def test_network_add_source_local(self):
        net = networks.Network()

        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])

        # Add agents to network.
        net.add_agent(agent1)
        net.add_agent(agent2)

        source = sources.RandomBinaryStringSource()
        self.db.add(source)
        net.add(source)
        source.connect_to(net.agents[0])

        assert len(net.vectors) == 1
        assert net.degrees == [0, 0]
        assert net.sources[0].outdegree == 1

    def test_network_add_agent(self):
        net = networks.Network()

        agent1 = agents.Agent()
        agent2 = agents.Agent()
        agent3 = agents.Agent()
        self.db.add_all([agent1, agent2, agent3])

        net.add_agent(agent1)
        net.add_agent(agent2)
        net.add_agent(agent3)

        assert len(net.agents) == 3
        assert len(net.vectors) == 0
        assert len(net.sources) == 0

    def test_network_downstream_nodes(self):
        net = networks.Network()

        node1 = models.Node()
        node2 = models.Node()
        agent1 = agents.Agent()
        agent2 = agents.ReplicatorAgent()
        source1 = models.Source()
        source2 = models.Source()

        self.db.add_all([node1, node2, agent1, agent2, source1, source2])
        net.add([node1, node2, agent1, agent2, source1, source2])

        node1.connect_to([node2, agent1, agent2])

        assert_raises(TypeError, node1.connect_to, source1)

        assert node1.get_downstream_nodes() == [node2, agent1, agent2]
        assert node1.outdegree == 3
        assert node1.get_downstream_nodes(type=agents.Agent) == [agent1, agent2]

        agent1.kill()
        agent2.fail()

        assert node1.get_downstream_nodes(status="dead") == [agent1]
        assert node1.get_downstream_nodes(status="failed") == [agent2]
        assert node1.get_downstream_nodes(status="alive") == [node2]
        assert node1.get_downstream_nodes(status="all") == [node2, agent1, agent2]

        assert_raises(ValueError, node1.get_downstream_nodes, status="blagjrg")

    def test_network_repr(self):
        net = networks.Network()

        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])

        net.add_agent(agent1)
        net.add_agent(agent2)

        source = sources.RandomBinaryStringSource()
        self.db.add(source)

        net.add(source)
        source.connect_to(net.agents)

        assert repr(net)[:8] == "<Network"
        assert repr(net)[15:] == "-base with 2 agents, 1 sources, 2 vectors>"

    def test_create_chain(self):
        net = networks.Chain()

        for i in range(4):
            agent = agents.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        source = sources.RandomBinaryStringSource()
        self.db.add(source)
        net.add(source)
        source.connect_to(net.agents[0])

        assert len(net.agents) == 4
        assert len(net.sources) == 1
        assert len(net.vectors) == 4
        assert net.agents[0].network == net
        assert net.sources[0].network == net

    def test_chain_repr(self):
        net = networks.Chain()

        for i in range(4):
            agent = agents.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        source = sources.RandomBinaryStringSource()
        self.db.add(source)
        net.add(source)

        source.connect_to(net.agents[0])

        assert repr(net)[:9] == "<Network-"
        assert repr(net)[15:] == "-chain with 4 agents, 1 sources, 4 vectors>"

    def test_create_fully_connected(self):
        net = networks.FullyConnected()
        for i in range(4):
            agent = agents.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        assert len(net.agents) == 4
        assert len(net.vectors) == 12
        assert net.degrees == [3, 3, 3, 3]

    def test_fully_connected_repr(self):
        net = networks.FullyConnected()
        for i in range(4):
            agent = agents.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        assert repr(net)[:9] == "<Network-"
        assert repr(net)[15:] == ("-fully-connected with 4 agents"
                                  ", 0 sources, 12 vectors>")

    def test_create_scale_free(self):
        net = networks.ScaleFree(m0=4, m=4)

        for i in range(4):
            agent = agents.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        assert len(net.agents) == 4
        assert len(net.vectors) == 12
        agent1 = agents.Agent()
        self.db.add(agent1)
        net.add_agent(agent1)
        assert len(net.agents) == 5
        assert len(net.vectors) == 20
        agent2 = agents.Agent()
        self.db.add(agent2)
        net.add_agent(agent2)
        assert len(net.agents) == 6
        assert len(net.vectors) == 28

    def test_scale_free_repr(self):
        net = networks.ScaleFree(m0=4, m=4)

        for i in range(6):
            agent = agents.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        assert repr(net)[:9] == "<Network-"
        assert repr(net)[15:] == ("-scale-free with 6 agents, "
                                  "0 sources, 28 vectors>")
