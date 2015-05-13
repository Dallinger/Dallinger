from wallace import networks, nodes, db, models
import random
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

    def test_node_failure(self):
        net = networks.Network()
        for _ in range(5):
            agent = nodes.Agent()
            self.db.add(agent)
            net.add(agent)
        agent = None
        source = nodes.Source()
        self.db.add(source)
        net.add(source)
        self.db.commit()

        assert len(net.nodes(type=nodes.Agent)) == 5

        random.choice(net.nodes(type=nodes.Agent)).fail()

        assert len(net.nodes(type=nodes.Agent)) == 4
        assert len(net.nodes(type=nodes.Agent, status="all")) == 5
        assert len(net.nodes()) == 5
        assert len(net.nodes(status="all")) == 6
        assert len(net.nodes(status="failed")) == 1

    def test_network_agents(self):
        net = networks.Network()
        assert len(net.nodes(type=nodes.Agent)) == 0

        agent = nodes.Agent()
        self.db.add(agent)

        net.add(agent)

        self.db.commit()

        assert net.nodes(type=nodes.Agent) == [agent]
        assert isinstance(net, models.Network)

    def test_network_sources(self):
        net = networks.Network()

        assert len(net.nodes(type=nodes.Source)) == 0

        source = nodes.Source()
        net.add(source)
        self.db.add(source)
        self.db.commit()

        assert net.nodes(type=nodes.Source) == [source]

    def test_network_nodes(self):
        net = models.Network()

        node1 = models.Node()
        node2 = models.Node()
        agent1 = nodes.Agent()
        agent2 = nodes.Agent()
        agent3 = nodes.Agent()

        net.add([node1, node2, agent1, agent2, agent3])
        self.db.add_all([node1, node2, agent1, agent2, agent3])
        self.db.commit()

        assert net.nodes() == [node1, node2, agent1, agent2, agent3]
        assert net.nodes(type=nodes.Agent) == [agent1, agent2, agent3]

        node1.die()
        agent1.fail()

        assert net.nodes() == [node2, agent2, agent3]
        assert net.nodes(status="all") == [node1, node2, agent1, agent2, agent3]
        assert net.nodes(status="dead") == [node1]
        assert net.nodes(type=nodes.Agent, status="all") == [agent1, agent2, agent3]

    def test_network_vectors(self):
        net = networks.Network()

        assert len(net.vectors()) == 0

        agent1 = nodes.Agent()
        agent2 = nodes.Agent()
        self.db.add_all([agent1, agent2])

        net.add(agent1)
        net.add(agent2)
        self.db.commit()

        agent1.connect_to(agent2)
        self.db.commit()

        assert len(net.vectors()) == 1
        assert net.vectors()[0].origin == agent1
        assert net.vectors()[0].destination == agent2

    def test_network_degrees(self):
        net = networks.Network()

        agent1 = nodes.Agent()
        agent2 = nodes.Agent()
        self.db.add_all([agent1, agent2])
        net.add(agent1)
        net.add(agent2)

        self.db.commit()

        assert [len(n.vectors(direction="outgoing")) for n in net.nodes()] == [0, 0]

        agent1.connect_to(agent2)

        assert [len(n.vectors(direction="outgoing")) for n in net.nodes()] == [1, 0]

    def test_network_add_source_global(self):
        net = networks.Network()

        agent1 = nodes.Agent()
        agent2 = nodes.Agent()

        # Add agents to network.
        net.add(agent1)
        net.add(agent2)

        self.db.add_all([agent1, agent2])
        self.db.commit()

        source = nodes.RandomBinaryStringSource()
        self.db.add(source)
        net.add(source)
        source.connect_to(net.nodes(type=nodes.Agent))

        assert len(net.vectors()) == 2
        assert source.network == net
        assert agent1.network == net
        assert [len(n.vectors(direction="outgoing")) for n in net.nodes(type=nodes.Agent)] == [0, 0]
        assert len(net.nodes(type=nodes.Source)[0].vectors(direction="outgoing")) == 2

    def test_network_add_source_local(self):
        net = networks.Network()

        agent1 = nodes.Agent()
        agent2 = nodes.Agent()

        # Add agents to network.
        net.add(agent1)
        net.add(agent2)

        self.db.add_all([agent1, agent2])
        self.db.commit()

        source = nodes.RandomBinaryStringSource()
        self.db.add(source)
        net.add(source)
        source.connect_to(net.nodes(type=nodes.Agent)[0])

        assert len(net.vectors()) == 1
        assert [len(n.vectors(direction="outgoing")) for n in net.nodes(type=nodes.Agent)] == [0, 0]
        assert len(net.nodes(type=nodes.Source)[0].vectors(direction="outgoing")) == 1

    def test_network_add_agent(self):
        net = networks.Network()

        agent1 = nodes.Agent()
        agent2 = nodes.Agent()
        agent3 = nodes.Agent()
        self.db.add_all([agent1, agent2, agent3])
        self.db.commit()

        net.add(agent1)
        net.add(agent2)
        net.add(agent3)

        self.db.commit()

        assert len(net.nodes(type=nodes.Agent)) == 3
        assert len(net.vectors()) == 0
        assert len(net.nodes(type=nodes.Source)) == 0

    def test_network_downstream_nodes(self):
        net = networks.Network()

        node1 = models.Node()
        node2 = models.Node()
        agent1 = nodes.Agent()
        agent2 = nodes.ReplicatorAgent()
        source1 = nodes.Source()
        source2 = nodes.Source()

        self.db.add_all([node1, node2, agent1, agent2, source1, source2])
        net.add([node1, node2, agent1, agent2, source1, source2])
        self.db.commit()

        node1.connect_to([node2, agent1, agent2])

        assert_raises(TypeError, node1.connect_to, source1)

        assert node1.neighbors(connection="to") == [node2, agent1, agent2]
        assert len(node1.vectors(direction="outgoing")) == 3
        assert node1.neighbors(connection="to", type=nodes.Agent) == [agent1, agent2]

        agent1.die()
        agent2.fail()

        # these assertions removed pending resolution of issue #164
        #assert node1.neighbors(connection="to", status="dead") == [agent1]
        #assert node1.neighbors(connection="to, status="failed") == [agent2]
        #assert node1.neighbors(connection="to, status="alive") == [node2]
        #assert node1.neighbors(connection="to, status="all") == [node2, agent1, agent2]

        assert_raises(ValueError, node1.neighbors, connection="to", status="blagjrg")

    def test_network_repr(self):
        net = networks.Network()

        agent1 = nodes.Agent()
        agent2 = nodes.Agent()
        self.db.add_all([agent1, agent2])

        net.add(agent1)
        net.add(agent2)

        self.db.commit()

        source = nodes.RandomBinaryStringSource()
        self.db.add(source)

        net.add(source)
        source.connect_to(net.nodes(type=nodes.Agent))

        assert repr(net)[:8] == "<Network"
        assert repr(net)[15:] == "-base with 3 nodes, 2 vectors, 0 infos, 0 transmissions and 0 transformations>"

    def test_create_chain(self):
        net = networks.Chain()

        for i in range(4):
            agent = nodes.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        source = nodes.RandomBinaryStringSource()
        self.db.add(source)
        net.add_source(source)

        assert len(net.nodes(type=nodes.Agent)) == 4
        assert len(net.nodes(type=nodes.Source)) == 1
        assert len(net.vectors()) == 4
        assert net.nodes(type=nodes.Agent)[0].network == net
        assert net.nodes(type=nodes.Source)[0].network == net

    def test_chain_repr(self):
        net = networks.Chain()

        for i in range(4):
            agent = nodes.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        source = nodes.RandomBinaryStringSource()
        self.db.add(source)
        net.add_source(source)

        assert repr(net)[:9] == "<Network-"
        assert repr(net)[15:] == "-chain with 5 nodes, 4 vectors, 0 infos, 0 transmissions and 0 transformations>"

    def test_create_fully_connected(self):
        net = networks.FullyConnected()
        for i in range(4):
            agent = nodes.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        assert len(net.nodes(type=nodes.Agent)) == 4
        assert len(net.vectors()) == 12
        assert [len(n.vectors(direction="outgoing")) for n in net.nodes(type=nodes.Agent)] == [3, 3, 3, 3]

    def test_fully_connected_repr(self):
        net = networks.FullyConnected()
        for i in range(4):
            agent = nodes.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        assert repr(net)[:9] == "<Network-"
        assert repr(net)[15:] == ("-fully-connected with 4 nodes, 12 vectors, 0 infos, 0 transmissions and 0 transformations>")

    def test_create_scale_free(self):
        m0 = 4
        m = 4
        net = networks.ScaleFree(m0=m0, m=m)

        for i in range(m0):
            agent = nodes.Agent()
            self.db.add(agent)
            net.add_agent(agent)
        self.db.commit()

        assert len(net.nodes(type=nodes.Agent)) == m0
        assert len(net.vectors()) == m0*(m0 - 1)

        agent1 = nodes.Agent()
        self.db.add(agent1)
        net.add_agent(agent1)
        self.db.commit()
        assert len(net.nodes(type=nodes.Agent)) == m0 + 1
        assert len(net.vectors()) == m0*(m0 - 1) + 2*m

        agent2 = nodes.Agent()
        self.db.add(agent2)
        net.add_agent(agent2)
        self.db.commit()
        assert len(net.nodes(type=nodes.Agent)) == m0 + 2
        assert len(net.vectors()) == m0*(m0 - 1) + 2*2*m

    def test_scale_free_repr(self):
        net = networks.ScaleFree(m0=4, m=4)

        for i in range(6):
            agent = nodes.Agent()
            self.db.add(agent)
            net.add_agent(agent)

        assert repr(net)[:9] == "<Network-"
        assert repr(net)[15:] == ("-scale-free with 6 nodes, 28 vectors, 0 infos, 0 transmissions and 0 transformations>")

    def test_discrete_generational(self):
        n_gens = 4
        gen_size = 4

        net = networks.DiscreteGenerational(generations=n_gens, generation_size=gen_size, initial_source=True)

        source = nodes.RandomBinaryStringSource()
        net.add(source)
        self.db.add(source)
        agents = []
        for i in range(n_gens*gen_size):
            agents.append(nodes.Agent())
            self.db.add(agents[-1])
            net.add(agents[-1])
            net.add_agent(agents[-1])

        assert len(net.nodes(type=nodes.Source)) == 1
        assert len(net.nodes(type=nodes.Agent)) == n_gens*gen_size

        for a in range(n_gens*gen_size):
            for b in range(n_gens*gen_size):
                a_gen = int((a)/float(gen_size))
                b_gen = int((b)/float(gen_size))
                if b_gen == (1+a_gen):
                    assert agents[a].is_connected(direction="to", other_node=agents[b])
                else:
                    assert (agents[a].is_connected(direction="to", other_node=agents[b]) is False)
                if a_gen == 0:
                    assert isinstance(agents[a].neighbors(connection="from")[0], nodes.Source)
