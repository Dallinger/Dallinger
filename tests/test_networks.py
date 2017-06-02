from dallinger import networks, nodes, models
import random
import pytest
from collections import defaultdict


class TestNetworks(object):

    def test_create_network(self, db_session):
        net = models.Network()
        assert isinstance(net, models.Network)

    def test_node_failure(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        for _ in range(5):
            nodes.Agent(network=net)
        nodes.Source(network=net)

        assert len(net.nodes(type=nodes.Agent)) == 5

        random.choice(net.nodes(type=nodes.Agent)).fail()

        assert len(net.nodes(type=nodes.Agent)) == 4
        assert len(net.nodes(type=nodes.Agent, failed="all")) == 5
        assert len(net.nodes()) == 5
        assert len(net.nodes(failed="all")) == 6
        assert len(net.nodes(failed=True)) == 1

    def test_network_agents(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        assert len(net.nodes(type=nodes.Agent)) == 0

        agent = nodes.Agent(network=net)

        assert net.nodes(type=nodes.Agent) == [agent]
        assert isinstance(net, models.Network)

    def test_network_base_add_node_not_implemented(self, db_session):
        net = models.Network()
        db_session.add(net)
        db_session.commit()
        node = models.Node(network=net)
        db_session.add(net)
        db_session.commit()
        with pytest.raises(NotImplementedError):
            net.add_node(node)

    def test_network_sources(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        assert len(net.nodes(type=nodes.Source)) == 0

        source = nodes.Source(network=net)

        assert net.nodes(type=nodes.Source) == [source]

    def test_network_nodes(self, db_session):
        net = models.Network()
        db_session.add(net)
        db_session.commit()

        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        agent1 = nodes.Agent(network=net)
        agent2 = nodes.Agent(network=net)
        agent3 = nodes.Agent(network=net)

        assert set([node1, node2, agent1, agent2, agent3]) == set(net.nodes())
        assert set([agent1, agent2, agent3]) == set(net.nodes(type=nodes.Agent))

        node1.fail()
        agent1.fail()

        assert set(net.nodes()) == set([node2, agent2, agent3])
        assert set(net.nodes(failed="all")) == set([node1, node2, agent1, agent2, agent3])
        assert set(net.nodes(failed=True)) == set([node1, agent1])
        assert set(net.nodes(type=nodes.Agent, failed="all")) == set([agent1, agent2, agent3])

    def test_network_vectors(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        assert len(net.vectors()) == 0

        agent1 = nodes.Agent(network=net)
        agent2 = nodes.Agent(network=net)

        agent1.connect(whom=agent2)

        assert len(net.vectors()) == 1
        assert net.vectors()[0].origin == agent1
        assert net.vectors()[0].destination == agent2

    def test_network_degrees(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        agent1 = nodes.Agent(network=net)
        agent2 = nodes.Agent(network=net)

        assert [len(n.vectors(direction="outgoing")) for n in net.nodes()] == [0, 0]

        agent1.connect(whom=agent2)

        assert 1 in [len(n.vectors(direction="outgoing")) for n in net.nodes()]
        assert 0 in [len(n.vectors(direction="outgoing")) for n in net.nodes()]

    def test_network_add_source_global(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        agent1 = nodes.Agent(network=net)
        nodes.Agent(network=net)
        # db_session.commit()

        source = nodes.RandomBinaryStringSource(network=net)
        source.connect(whom=net.nodes(type=nodes.Agent))

        assert len(net.vectors()) == 2
        assert source.network == net
        assert agent1.network == net
        assert [len(n.vectors(direction="outgoing")) for n in net.nodes(type=nodes.Agent)] == [0, 0]
        assert len(net.nodes(type=nodes.Source)[0].vectors(direction="outgoing")) == 2

    def test_network_add_source_local(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        nodes.Agent(network=net)
        nodes.Agent(network=net)

        source = nodes.RandomBinaryStringSource(network=net)
        source.connect(whom=net.nodes(type=nodes.Agent)[0])

        assert len(net.vectors()) == 1
        assert [len(n.vectors(direction="outgoing")) for n in net.nodes(type=nodes.Agent)] == [0, 0]
        assert len(net.nodes(type=nodes.Source)[0].vectors(direction="outgoing")) == 1

    def test_network_add_node(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        nodes.Agent(network=net)
        nodes.Agent(network=net)
        nodes.Agent(network=net)

        assert len(net.nodes(type=nodes.Agent)) == 3
        assert len(net.vectors()) == 0
        assert len(net.nodes(type=nodes.Source)) == 0

    def test_network_downstream_nodes(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        agent1 = nodes.Agent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        source1 = nodes.Source(network=net)
        nodes.Source(network=net)

        node1.connect(whom=[node2, agent1, agent2])

        pytest.raises(TypeError, node1.connect, whom=source1)

        assert set(node1.neighbors(direction="to")) == set([node2, agent1, agent2])
        assert len(node1.vectors(direction="outgoing")) == 3
        assert set(node1.neighbors(direction="to", type=nodes.Agent)) == set([agent1, agent2])

        agent1.fail()
        agent2.fail()

        pytest.raises(ValueError, node1.neighbors, direction="ghbhfgjd")

    def test_network_repr(self, db_session):
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        nodes.Agent(network=net)
        nodes.Agent(network=net)

        source = nodes.RandomBinaryStringSource(network=net)
        source.connect(whom=net.nodes(type=nodes.Agent))

        assert repr(net) == (
            "<Network-" + str(net.id) + "-network with 3 nodes, 2 vectors, "
            "0 infos, 0 transmissions and 0 transformations>"
        )

    def test_create_chain(self, db_session):
        net = networks.Chain()
        db_session.add(net)
        db_session.commit()

        source = nodes.RandomBinaryStringSource(network=net)
        net.add_node(source)

        for i in range(4):
            agent = nodes.Agent(network=net)
            net.add_node(agent)

        assert len(net.nodes(type=nodes.Agent)) == 4
        assert len(net.nodes(type=nodes.Source)) == 1
        assert len(net.vectors()) == 4
        assert net.nodes(type=nodes.Agent)[0].network == net
        assert net.nodes(type=nodes.Source)[0].network == net

    def test_chain_repr(self, db_session):
        net = networks.Chain()
        db_session.add(net)
        db_session.commit()

        source = nodes.RandomBinaryStringSource(network=net)
        net.add_node(source)

        for i in range(4):
            agent = nodes.ReplicatorAgent(network=net)
            net.add_node(agent)
        db_session.commit()

        assert repr(net) == (
            "<Network-" + str(net.id) + "-chain with 5 nodes, 4 vectors, "
            "0 infos, 0 transmissions and 0 transformations>"
        )

    def test_create_fully_connected(self, db_session):
        net = networks.FullyConnected()
        db_session.add(net)
        db_session.commit()

        for i in range(4):
            agent = nodes.Agent(network=net)
            net.add_node(agent)

        assert len(net.nodes(type=nodes.Agent)) == 4
        assert len(net.vectors()) == 12
        assert [
            len(n.vectors(direction="outgoing"))
            for n in net.nodes(type=nodes.Agent)
        ] == [3, 3, 3, 3]

    def test_create_empty(self, db_session):
        """Empty networks should have nodes, but no edges."""
        net = networks.Empty()
        db_session.add(net)
        db_session.commit()

        for i in range(10):
            agent = nodes.Agent(network=net)
            net.add_node(agent)

        assert len(net.nodes(type=nodes.Agent)) == 10
        assert len(net.vectors()) == 0

    def test_create_empty_with_source(self, db_session):
        """A sourced empty network should have nodes and an edge for each."""
        net = networks.Empty()
        db_session.add(net)
        db_session.commit()

        for i in range(10):
            agent = nodes.Agent(network=net)
            net.add_node(agent)

        source = nodes.Source(network=net)
        net.add_source(source)

        assert len(net.nodes(type=nodes.Agent)) == 10
        assert len(net.vectors()) == 10

    def test_fully_connected_repr(self, db_session):
        net = networks.FullyConnected()
        db_session.add(net)
        db_session.commit()
        for i in range(4):
            agent = nodes.Agent(network=net)
            net.add_node(agent)

        assert repr(net) == (
            "<Network-" + str(net.id) + "-fully-connected with 4 nodes, 12 vectors, "
            "0 infos, 0 transmissions and 0 transformations>"
        )

    def test_create_scale_free(self, db_session):
        m0 = 4
        m = 4
        net = networks.ScaleFree(m0=m0, m=m)
        db_session.add(net)
        db_session.commit()

        for i in range(m0):
            agent = nodes.Agent(network=net)
            net.add_node(agent)

        assert len(net.nodes(type=nodes.Agent)) == m0
        assert len(net.vectors()) == m0 * (m0 - 1)

        agent1 = nodes.Agent(network=net)
        net.add_node(agent1)
        assert len(net.nodes(type=nodes.Agent)) == m0 + 1
        assert len(net.vectors()) == m0 * (m0 - 1) + 2 * m

        agent2 = nodes.Agent(network=net)
        net.add_node(agent2)
        assert len(net.nodes(type=nodes.Agent)) == m0 + 2
        assert len(net.vectors()) == m0 * (m0 - 1) + 2 * 2 * m

    def test_scale_free_repr(self, db_session):
        net = networks.ScaleFree(m0=4, m=4)
        db_session.add(net)
        db_session.commit()

        for i in range(6):
            agent = nodes.Agent(network=net)
            net.add_node(agent)

        assert repr(net) == (
            "<Network-" + str(net.id) + "-scale-free with 6 nodes, 28 vectors, "
            "0 infos, 0 transmissions and 0 transformations>"
        )

    def test_create_sequential_microsociety(self, db_session):
        """Create a sequential microsociety."""
        net = networks.SequentialMicrosociety(n=3)
        db_session.add(net)
        db_session.commit()

        net.add_node(nodes.RandomBinaryStringSource(network=net))

        agent1 = nodes.Agent(network=net)
        net.add_node(agent1)

        agent2 = nodes.Agent(network=net)
        net.add_node(agent2)

        agent3 = nodes.Agent(network=net)
        net.add_node(agent3)

        agent4 = nodes.Agent(network=net)
        net.add_node(agent4)

        agent5 = nodes.Agent(network=net)
        net.add_node(agent5)

        agent6 = nodes.Agent(network=net)
        net.add_node(agent6)

        assert len(agent1.vectors(direction="outgoing")) == 2
        assert len(agent2.vectors(direction="outgoing")) == 2
        assert len(agent3.vectors(direction="outgoing")) == 2

        assert agent2.is_connected(direction="to", whom=agent3)
        assert agent2.is_connected(direction="to", whom=agent4)
        assert not agent2.is_connected(direction="to", whom=agent5)

        assert agent3.is_connected(direction="to", whom=agent4)
        assert agent3.is_connected(direction="to", whom=agent5)
        assert not agent3.is_connected(direction="to", whom=agent6)


class GenerationalAgent(nodes.Agent):

    from sqlalchemy.ext.hybrid import hybrid_property

    __mapper_args__ = {"polymorphic_identity": "test_agent"}

    @hybrid_property
    def generation(self):
        """Convert property2 to genertion."""
        return int(self.property2)

    @generation.setter
    def generation(self, generation):
        """Make generation settable."""
        self.property2 = repr(generation)

    @generation.expression
    def generation(self):
        """Make generation queryable."""
        from sqlalchemy import Integer
        from sqlalchemy.sql.expression import cast
        return cast(self.property2, Integer)


class TestDiscreteGenerational(TestNetworks):

    n_gens = 4
    gen_size = 4

    @pytest.fixture
    def initial_source(self):
        return True

    @pytest.fixture
    def net(self, db_session, initial_source):
        net = networks.DiscreteGenerational(
            generations=self.n_gens,
            generation_size=self.gen_size,
            initial_source=initial_source)
        db_session.add(net)
        db_session.commit()

        return net

    def _fill(self, net):
        total_nodes = net.generations * net.generation_size
        by_gen = defaultdict(list)
        for i in range(total_nodes):
            agent = GenerationalAgent(network=net)
            agent.fitness = i + .1
            net.add_node(agent)
            by_gen[agent.generation].append(agent)

        return by_gen

    def test_initial_source_attr_true(self, net):
        assert net.initial_source

    @pytest.mark.parametrize('initial_source', [False])
    def test_initial_source_attr_false(self, net):
        assert not net.initial_source

    @pytest.mark.parametrize('initial_source', [True, False])
    def test_add_node_fills_network_dimensions(self, net):
        nodes.RandomBinaryStringSource(network=net)
        self._fill(net)

        assert len(net.nodes(type=nodes.Source)) == 1
        assert len(net.nodes(type=nodes.Agent)) == self.n_gens * self.gen_size

    def test_add_node_with_initial_source_true(self, net):
        source = nodes.RandomBinaryStringSource(network=net)
        by_gen = self._fill(net)

        first_generation = by_gen[0]
        subsequent_generations = {gen: by_gen[gen] for gen in by_gen.keys() if gen > 0}

        # First generation is conncted to source
        for agent in first_generation:
            assert agent.neighbors(direction='from') == [source]

        # Subsequent generations get assigned a single random parent
        # from the previous generation
        for generation, agents in subsequent_generations.items():
            for agent in agents:
                parents = agent.neighbors(direction='from')
                assert len(parents) == 1
                assert parents[0] in by_gen[agent.generation - 1]

    @pytest.mark.parametrize('initial_source', [False])
    def test_add_node_with_initial_source_false(self, net):
        source = nodes.RandomBinaryStringSource(network=net)
        first_generation = self._fill(net)[0]

        # First generation is NOT conncted to source
        for agent in first_generation:
            assert source not in agent.neighbors(direction='from')
