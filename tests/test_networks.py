import random
from collections import defaultdict

import pytest

from dallinger import models, networks, nodes


class TestNetworks(object):
    def test_create_network(self, db_session):
        net = models.Network()
        assert isinstance(net, models.Network)

    def test_has_a_big_default_max_size(self, a):
        assert a.network().max_size > 100000

    def test_not_full_with_zero_nodes(self, a):
        net = a.network(max_size=1)
        assert not net.full

    def test_not_full_if_nodes_fewer_than_max_size(self, a):
        net = a.network(max_size=2)
        nodes.Agent(network=net)
        assert not net.full

    def test_full_if_nodes_equal_max_size(self, a):
        net = a.network(max_size=1)
        nodes.Agent(network=net)
        assert net.full

    def test_node_failure(self, db_session):
        net = networks.Network()
        db_session.add(net)

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

    def test_network_failure_captures_cascade_in_failure_reason(self, a):
        net = a.network()
        node1 = a.node(network=net)
        node2 = a.node(network=net)
        node1.connect(whom=node2)
        info = a.info(origin=node1)
        node1.transmit(what=node1.infos()[0], to_whom=node2)
        transmission = node1.transmissions()[0]
        vector = node1.vectors()[0]

        net.fail()

        assert net.failed_reason is None
        assert node1.failed_reason == "->Network1"
        assert node2.failed_reason == "->Network1"
        # Can't know which node is failed first, so check for either route:
        assert info.failed_reason in {"->Network1->Node1", "->Network1->Node2"}
        assert vector.failed_reason in {"->Network1->Node1", "->Network1->Node2"}
        assert transmission.failed_reason in {
            "->Network1->Node1->Vector1",
            "->Network1->Node2->Vector1",
        }

    def test_network_failure_propagates_explicit_failure_reason(self, a):
        net = a.network()
        node1 = a.node(network=net)
        node2 = a.node(network=net)
        node1.connect(whom=node2)
        info = a.info(origin=node1)
        node1.transmit(what=node1.infos()[0], to_whom=node2)
        transmission = node1.transmissions()[0]
        vector = node1.vectors()[0]

        net.fail(reason="Boom!")

        assert net.failed_reason == "Boom!"
        assert node1.failed_reason == "Boom!->Network1"
        assert node2.failed_reason == "Boom!->Network1"
        # Can't know which node is failed first, so check for either route:
        assert info.failed_reason in {
            "Boom!->Network1->Node1",
            "Boom!->Network1->Node2",
        }
        assert vector.failed_reason in {
            "Boom!->Network1->Node1",
            "Boom!->Network1->Node2",
        }
        assert transmission.failed_reason in {
            "Boom!->Network1->Node1->Vector1",
            "Boom!->Network1->Node2->Vector1",
        }

    def test_network_agents(self, db_session):
        net = networks.Network()
        db_session.add(net)

        assert len(net.nodes(type=nodes.Agent)) == 0

        agent = nodes.Agent(network=net)

        assert net.nodes(type=nodes.Agent) == [agent]
        assert isinstance(net, models.Network)

    def test_network_base_add_node_not_implemented(self, db_session):
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        db_session.add(net)
        with pytest.raises(NotImplementedError):
            net.add_node(node)

    def test_network_sources(self, db_session):
        net = networks.Network()
        db_session.add(net)

        assert len(net.nodes(type=nodes.Source)) == 0

        source = nodes.Source(network=net)

        assert net.nodes(type=nodes.Source) == [source]

    def test_network_nodes(self, db_session):
        net = models.Network()
        db_session.add(net)

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
        assert set(net.nodes(failed="all")) == set(
            [node1, node2, agent1, agent2, agent3]
        )
        assert set(net.nodes(failed=True)) == set([node1, agent1])
        assert set(net.nodes(type=nodes.Agent, failed="all")) == set(
            [agent1, agent2, agent3]
        )

    def test_network_vectors(self, db_session):
        net = networks.Network()
        db_session.add(net)

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

        agent1 = nodes.Agent(network=net)
        agent2 = nodes.Agent(network=net)

        assert [len(n.vectors(direction="outgoing")) for n in net.nodes()] == [0, 0]

        agent1.connect(whom=agent2)

        assert 1 in [len(n.vectors(direction="outgoing")) for n in net.nodes()]
        assert 0 in [len(n.vectors(direction="outgoing")) for n in net.nodes()]

    def test_network_add_source_global(self, db_session):
        net = networks.Network()
        db_session.add(net)

        agent1 = nodes.Agent(network=net)
        nodes.Agent(network=net)

        source = nodes.RandomBinaryStringSource(network=net)
        source.connect(whom=net.nodes(type=nodes.Agent))

        assert len(net.vectors()) == 2
        assert source.network == net
        assert agent1.network == net
        assert [
            len(n.vectors(direction="outgoing")) for n in net.nodes(type=nodes.Agent)
        ] == [0, 0]
        assert len(net.nodes(type=nodes.Source)[0].vectors(direction="outgoing")) == 2

    def test_network_add_source_local(self, db_session):
        net = networks.Network()
        db_session.add(net)

        nodes.Agent(network=net)
        nodes.Agent(network=net)

        source = nodes.RandomBinaryStringSource(network=net)
        source.connect(whom=net.nodes(type=nodes.Agent)[0])

        assert len(net.vectors()) == 1
        assert [
            len(n.vectors(direction="outgoing")) for n in net.nodes(type=nodes.Agent)
        ] == [0, 0]
        assert len(net.nodes(type=nodes.Source)[0].vectors(direction="outgoing")) == 1

    def test_network_add_node(self, db_session):
        net = networks.Network()
        db_session.add(net)

        nodes.Agent(network=net)
        nodes.Agent(network=net)
        nodes.Agent(network=net)

        assert len(net.nodes(type=nodes.Agent)) == 3
        assert len(net.vectors()) == 0
        assert len(net.nodes(type=nodes.Source)) == 0

    def test_network_downstream_nodes(self, db_session):
        net = networks.Network()
        db_session.add(net)

        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        agent1 = nodes.Agent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        source1 = nodes.Source(network=net)
        nodes.Source(network=net)

        node1.connect(whom=[node2, agent1, agent2])

        assert pytest.raises(TypeError, node1.connect, whom=source1)

        assert set(node1.neighbors(direction="to")) == set([node2, agent1, agent2])
        assert len(node1.vectors(direction="outgoing")) == 3
        assert set(node1.neighbors(direction="to", type=nodes.Agent)) == set(
            [agent1, agent2]
        )

        agent1.fail()
        agent2.fail()

        assert pytest.raises(ValueError, node1.neighbors, direction="ghbhfgjd")

    def test_network_repr(self, db_session):
        net = networks.Network()
        db_session.add(net)

        nodes.Agent(network=net)
        nodes.Agent(network=net)

        source = nodes.RandomBinaryStringSource(network=net)
        source.connect(whom=net.nodes(type=nodes.Agent))

        assert repr(net) == (
            "<Network-" + str(net.id) + "-network with 3 nodes, 2 vectors, "
            "0 infos, 0 transmissions and 0 transformations>"
        )


class TestChain(object):
    def test_nodes_are_connected_to_their_successor_if_added_immediately(self, a):
        chain = a.chain()
        old = a.node(network=chain)
        middle = a.node(network=chain)
        chain.add_node(middle)
        new = a.node(network=chain)
        chain.add_node(new)

        assert new.neighbors() == []
        assert middle.neighbors() == [new]
        assert old.neighbors() == [middle]

    def test_nodes_are_connected_to_newest_node_if_added_later(self, a):
        # Not really a chain in this case!
        chain = a.chain()
        old = a.node(network=chain)
        middle = a.node(network=chain)
        new = a.node(network=chain)
        chain.add_node(old)
        chain.add_node(middle)
        chain.add_node(new)

        assert old.neighbors() == []
        assert middle.neighbors() == [new]
        assert new.neighbors() == [old, middle]

    def test_source_can_be_added_implicitly_at_tail(self, a):
        chain = a.chain()
        source = a.source(network=chain)
        node = a.node(network=chain)
        chain.add_node(node)

        assert source.neighbors() == [node]
        assert node.neighbors() == []

    def test_cannot_add_a_source_once_other_nodes_exist(self, a):
        chain = a.chain()
        a.node(network=chain)
        source = a.source(network=chain)
        with pytest.raises(Exception) as exc_info:
            chain.add_node(source)
            assert exc_info.match("Chain network already has a node")

    def test_repr(self, a):
        chain = a.chain()
        a.source(network=chain)  # added implicitly with next node added.

        for _ in range(4):
            chain.add_node(a.node(network=chain))

        assert repr(chain) == (
            "<Network-{}-chain with 5 nodes, 4 vectors, "
            "0 infos, 0 transmissions and 0 transformations>".format(chain.id)
        )


class TestDelayedChain(object):
    def test_parent_is_always_source_for_first_11_nodes_when_source_exists(self, a):
        net = a.delayed_chain()
        source = a.source(network=net)

        for _ in range(10):
            net.add_node(a.node(network=net))

        assert len(source.neighbors()) == 10
        assert not any([node.neighbors() for node in net.nodes() if node is not source])

    def test_no_parents_for_first_11_nodes_if_no_source_in_network(self, a):
        net = a.delayed_chain()

        for _ in range(11):
            net.add_node(a.node(network=net))

        assert not any([node.neighbors() for node in net.nodes()])

    def test_starts_assigning_newest_sibling_as_parent_after_11_nodes_in_network(
        self, a
    ):
        net = a.delayed_chain()

        for _ in range(12):
            net.add_node(a.node(network=net))

        nodes_with_parents = [node for node in net.nodes() if node.neighbors()]

        assert len(nodes_with_parents) == 1

    def test_nodes_beyond_count_of_11_get_newest_sibling_as_parent(self, a):
        net = a.delayed_chain()
        source = a.source(network=net)

        for _ in range(15):
            net.add_node(a.node(network=net))

        non_source_nodes = [node for node in net.nodes() if node is not source]
        non_source_nodes.sort(key=lambda n: n.creation_time)
        added_after_11_existed = non_source_nodes[10:]

        for index, node in enumerate(added_after_11_existed):
            try:
                next_node = added_after_11_existed[index + 1]
            except IndexError:
                break
            assert next_node.is_connected(direction="from", whom=node)


class TestFullyConnected(object):
    def test_nodes_get_connected_bidirectionally(self, a):
        connected = a.fully_connected()
        node1 = a.node(network=connected)
        node2 = a.node(network=connected)
        node3 = a.node(network=connected)

        connected.add_node(node1)
        connected.add_node(node2)
        connected.add_node(node3)

        assert len(connected.vectors()) == 6

        assert node1.is_connected(direction="both", whom=node2)
        assert node1.is_connected(direction="both", whom=node3)

        assert node2.is_connected(direction="both", whom=node1)
        assert node2.is_connected(direction="both", whom=node3)

        assert node3.is_connected(direction="both", whom=node1)
        assert node3.is_connected(direction="both", whom=node2)

        outgoing_connections_per_node = [
            len(n.vectors(direction="outgoing")) for n in connected.nodes()
        ]
        assert outgoing_connections_per_node == [2, 2, 2]

    def test_sources_get_connected_to_but_do_not_connect_back(self, a):
        connected = a.fully_connected()
        source = a.source(network=connected)
        node2 = a.node(network=connected)
        node3 = a.node(network=connected)

        connected.add_node(node2)
        connected.add_node(node3)

        assert len(connected.vectors()) == 4

        assert node2.is_connected(direction="both", whom=node3)
        assert node3.is_connected(direction="both", whom=node2)

        assert source.is_connected(direction="to", whom=node2)
        assert source.is_connected(direction="to", whom=node3)

    def test_repr(self, a):
        connected = a.fully_connected()
        for _ in range(4):
            connected.add_node(a.node(network=connected))

        assert repr(connected) == (
            "<Network-{}-fully-connected with 4 nodes, 12 vectors, "
            "0 infos, 0 transmissions and 0 transformations>".format(connected.id)
        )


class TestEmpty(object):
    def test_create_empty(self, a):
        """Empty networks should have nodes, but no edges."""
        net = a.empty()

        for _ in range(10):
            net.add_node(a.node(network=net))

        assert len(net.nodes()) == 10
        assert len(net.vectors()) == 0

    def test_create_empty_with_source(self, a):
        """A sourced empty network should have nodes and an edge for each."""
        net = a.empty()

        for i in range(10):
            net.add_node(a.node(network=net))

        net.add_source(a.source(network=net))

        assert len(net.nodes()) == 11
        assert len(net.vectors()) == 10


class TestBurst(object):
    def test_all_subsequent_nodes_connect_only_to_first_one(self, a):
        burst = a.burst()
        center = a.node(network=burst)
        edge1 = a.node(network=burst)
        edge2 = a.node(network=burst)

        # Note that the oldest node is linked implicitly when the next is added
        burst.add_node(edge1)
        burst.add_node(edge2)

        assert center.neighbors() == [edge1, edge2]
        assert edge1.neighbors() == []
        assert edge2.neighbors() == []

    def test_adding_initial_node_is_harmless_noop(self, a):
        network = a.burst()
        network.add_node(a.node(network=network))

    def test_adding_oldest_node_raises_trying_to_connect_it_to_itself(self, a):
        network = a.burst()
        oldest = a.node(network=network)
        newest = a.node(network=network)

        network.add_node(newest)
        with pytest.raises(ValueError) as exc_info:
            network.add_node(oldest)
            assert exc_info.match("cannot connect to itself")


class TestStar(object):
    def test_all_subsequent_nodes_connect_bidirectionally_to_first_one(self, a):
        star = a.star()
        center = a.node(network=star)
        edge1 = a.node(network=star)
        edge2 = a.node(network=star)

        # Note that the oldest node is linked implicitly when the next is added
        star.add_node(edge1)
        star.add_node(edge2)

        assert center.neighbors() == [edge1, edge2]
        assert edge1.neighbors() == [center]
        assert edge2.neighbors() == [center]

    def test_adding_initial_node_is_harmless_noop(self, a):
        network = a.star()
        network.add_node(a.node(network=network))

    def test_adding_oldest_node_raises_trying_to_connect_it_to_itself(self, a):
        network = a.star()
        oldest = a.node(network=network)
        newest = a.node(network=network)

        network.add_node(newest)
        with pytest.raises(ValueError) as exc_info:
            network.add_node(oldest)
            assert exc_info.match("cannot connect to itself")


@pytest.mark.slow
class TestScaleFree(object):
    def test_create_scale_free(self, a):
        m0 = 4
        m = 4
        net = a.scale_free(m0=m0, m=m)

        for _ in range(m0):
            net.add_node(a.agent(network=net))

        assert len(net.nodes(type=nodes.Agent)) == m0
        assert len(net.vectors()) == m0 * (m0 - 1)

        net.add_node(a.agent(network=net))
        assert len(net.nodes(type=nodes.Agent)) == m0 + 1
        assert len(net.vectors()) == m0 * (m0 - 1) + 2 * m

        net.add_node(a.agent(network=net))
        assert len(net.nodes(type=nodes.Agent)) == m0 + 2
        assert len(net.vectors()) == m0 * (m0 - 1) + 2 * 2 * m

    def test_repr(self, a):
        net = a.scale_free(m0=4, m=4)

        for _ in range(6):
            net.add_node(a.agent(network=net))

        assert repr(net) == (
            "<Network-{}-scale-free with 6 nodes, 28 vectors, "
            "0 infos, 0 transmissions and 0 transformations>".format(net.id)
        )


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


@pytest.mark.slow
class TestDiscreteGenerational(object):
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
            initial_source=initial_source,
        )
        db_session.add(net)

        return net

    def _fill(self, net):
        total_nodes = net.generations * net.generation_size
        by_gen = defaultdict(list)
        for i in range(total_nodes):
            agent = GenerationalAgent(network=net)
            agent.fitness = i + 0.1
            net.add_node(agent)
            by_gen[agent.generation].append(agent)

        return by_gen

    def test_initial_source_attr_true(self, net):
        assert net.initial_source

    @pytest.mark.parametrize("initial_source", [False])
    def test_initial_source_attr_false(self, net):
        assert not net.initial_source

    @pytest.mark.parametrize("initial_source", [True, False])
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
            assert agent.neighbors(direction="from") == [source]

        # Subsequent generations get assigned a single random parent
        # from the previous generation
        for generation, agents in subsequent_generations.items():
            for agent in agents:
                parents = agent.neighbors(direction="from")
                assert len(parents) == 1
                assert parents[0] in by_gen[agent.generation - 1]

    @pytest.mark.parametrize("initial_source", [False])
    def test_add_node_with_initial_source_false(self, net):
        source = nodes.RandomBinaryStringSource(network=net)
        first_generation = self._fill(net)[0]

        # First generation is NOT conncted to source
        for agent in first_generation:
            assert source not in agent.neighbors(direction="from")

    def test_assigns_generation_correctly_when_addition_non_agent_included(self, net):
        nodes.RandomBinaryStringSource(network=net)
        net.max_size += 1  # Necessary hack if you want to add another Node.
        nodes.Environment(network=net)

        by_gen = self._fill(net)

        for generation in by_gen.values():
            assert len(generation) == net.generation_size


class TestSequentialMicrosociety(object):
    def test_n_property_type_marshalling(self, a):
        net = a.sequential_microsociety(n=3)
        assert net.n == 3

    def test_new_nodes_connected_to_active_nodes_only(self, a):
        """Create a sequential microsociety."""
        net = a.sequential_microsociety(n=3)

        agent1 = a.agent(network=net)
        net.add_node(agent1)

        agent2 = a.agent(network=net)
        net.add_node(agent2)

        agent3 = a.agent(network=net)
        net.add_node(agent3)

        agent4 = a.agent(network=net)
        net.add_node(agent4)

        agent5 = a.agent(network=net)
        net.add_node(agent5)

        agent6 = a.agent(network=net)
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


class TestSplitSampleNetwork(object):
    def test_sample_splitting(self, a):
        nets = [a.split_sample() for i in range(100)]
        sets = [net.exploratory for net in nets]
        assert sum(sets) != 0
        assert sum(sets) != 100
