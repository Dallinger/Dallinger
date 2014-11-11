from wallace import networks, agents, db, sources


class TestNetworks(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def test_create_network(self):
        net = networks.Network(agents.Agent, self.db)
        assert net.db == self.db

    def test_network_agents(self):
        net = networks.Network(agents.Agent, self.db)
        assert len(net.agents) == 0

        agent = agents.Agent()
        self.db.add(agent)
        self.db.commit()

        assert net.agents == [agent]

    def test_network_sources(self):
        net = networks.Network(agents.Agent, self.db)
        assert len(net.sources) == 0

        source = sources.Source()
        self.db.add(source)
        self.db.commit()

        assert net.sources == [source]

    def test_network_links(self):
        net = networks.Network(agents.Agent, self.db)
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
        net = networks.Network(agents.Agent, self.db)
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])
        self.db.commit()

        assert net.get_degrees() == [0, 0]

        agent1.connect_to(agent2)
        self.db.commit()

        assert net.get_degrees() == [1, 0]

    def test_network_add_global_source(self):
        net = networks.Network(agents.Agent, self.db)
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])
        self.db.commit()

        source = sources.RandomBinaryStringSource()
        net.add_global_source(source)

        assert len(net.links) == 2
        assert net.get_degrees() == [0, 0]
        assert net.sources[0].outdegree == 2

    def test_network_add_local_source(self):
        net = networks.Network(agents.Agent, self.db)
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.db.add_all([agent1, agent2])
        self.db.commit()

        source = sources.RandomBinaryStringSource()
        net.add_local_source(source, agent1)

        assert len(net.links) == 1
        assert net.get_degrees() == [0, 0]
        assert net.sources[0].outdegree == 1

    def test_network_trigger_source(self):
        net = networks.Network(agents.Agent, self.db)
        agent1 = agents.ReplicatorAgent()
        agent2 = agents.ReplicatorAgent()
        self.db.add_all([agent1, agent2])
        self.db.commit()

        source = sources.RandomBinaryStringSource()
        net.add_global_source(source)

        agent1.receive_all()
        agent2.receive_all()
        self.db.commit()

        assert agent1.info is None
        assert agent2.info is None

        net.trigger_source(source)

        agent1.receive_all()
        agent2.receive_all()
        self.db.commit()

        assert agent1.info
        assert agent2.info
        assert len(source.outgoing_transmissions) == 2

    def test_network_add_agent(self):
        net = networks.Network(agents.Agent, self.db)
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        agent3 = agents.Agent()
        net.add_agent(agent1)
        net.add_agent(agent2)
        net.add_agent(agent3)
        assert len(net.agents) == 3
        assert len(net.links) == 0
        assert len(net.sources) == 0

    def test_network_repr(self):
        net = networks.Network(agents.Agent, self.db)
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        net.add_agent(agent1)
        net.add_agent(agent2)

        source = sources.RandomBinaryStringSource()
        net.add_global_source(source)

        assert repr(net) == "<Network with 2 agents, 1 sources, 2 links>"

    def test_create_chain(self):
        net = networks.Chain(agents.Agent, self.db, 4)
        source = sources.RandomBinaryStringSource()
        net.add_local_source(source, net.first_agent)
        assert len(net) == 4
        assert len(net.links) == 4

    def test_empty_chain_last_agent(self):
        net = networks.Chain(agents.Agent, self.db, 0)
        assert net.last_agent is None

    def test_empty_chain_first_agent(self):
        net = networks.Chain(agents.Agent, self.db, 0)
        assert net.first_agent is None

    def test_chain_first_agent(self):
        net = networks.Chain(agents.Agent, self.db, 4)
        assert net.first_agent is not None
        assert net.first_agent.indegree == 0
        assert net.first_agent.outdegree == 1

    def test_chain_last_agent(self):
        net = networks.Chain(agents.Agent, self.db, 4)
        assert net.last_agent is not None
        assert net.last_agent.indegree == 1
        assert net.last_agent.outdegree == 0

    def test_chain_repr(self):
        net = networks.Chain(agents.Agent, self.db, 4)
        source = sources.RandomBinaryStringSource()
        net.add_local_source(source, net.first_agent)
        assert repr(net) == "<Chain with 4 agents, 1 sources, 4 links>"

    def test_create_fully_connected(self):
        net = networks.FullyConnected(agents.Agent, self.db, 4)
        assert len(net) == 4
        assert len(net.links) == 12
        assert net.get_degrees() == [3, 3, 3, 3]

    def test_fully_connected_repr(self):
        net = networks.FullyConnected(agents.Agent, self.db, 4)
        assert (
            repr(net) == "<FullyConnected with 4 agents, 0 sources, 12 links>")

    def test_create_scale_free(self):
        net = networks.ScaleFree(agents.Agent, self.db, 4, m0=4, m=4)
        assert len(net.agents) == 4
        assert len(net.links) == 12
        net.add_agent()
        assert len(net.agents) == 5
        assert len(net.links) == 20
        net.add_agent()
        assert len(net.agents) == 6
        assert len(net.links) == 28

    def test_scale_free_repr(self):
        net = networks.ScaleFree(agents.Agent, self.db, 6, m0=4, m=4)
        assert repr(net) == "<ScaleFree with 6 agents, 0 sources, 28 links>"
