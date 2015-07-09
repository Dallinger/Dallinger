from __future__ import print_function
import sys
from datetime import datetime
from wallace import models, db, nodes
from nose.tools import raises, assert_raises


class TestModels(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_models(self):

        """
        Test Networks
        """
        print("")
        print("Testing models: Network...", end="\r")
        sys.stdout.flush()

        # create test network:

        net = models.Network()
        self.db.add(net)
        self.db.commit()

        net = models.Network.query.one()

        assert repr(net) == "<Network-1-base with 0 nodes, 0 vectors, 0 infos, 0 transmissions and 0 transformations>"

        from wallace.nodes import Agent, Source

        for i in range(5):
            # nodes
            node = models.Node(network=net)
            agent = Agent(network=net, participant_uuid=i)
            source = Source(network=net)

            # vectors
            source.connect(direction="to", whom=agent)
            agent.connect(direction="both", whom=node)

            # infos
            info = models.Info(origin=agent, contents=str(i))
            from wallace.information import Gene
            gene = Gene(origin=source, contents=str(i))

            if i in [0, 1]:
                source.transmit(what=models.Info)
                agent.receive()
                agent.transmit(what=Gene)

                models.Transformation(info_in=gene, info_out=info)
            else:
                agent.transmit(to_whom=node)

        assert repr(net) == "<Network-1-base with 15 nodes, 15 vectors, 10 infos, 5 transmissions and 2 transformations>"

        # Test Network sql columns

        assert isinstance(net.uuid, int)
        assert net.uuid == 1
        assert isinstance(net.creation_time, datetime)
        assert isinstance(net.max_size, int)
        assert isinstance(net.full, bool)
        assert net.full is False
        assert isinstance(net.role, unicode)
        assert net.role == "default"
        assert net.property1 is None
        assert net.property2 is None
        assert net.property3 is None
        assert net.property4 is None
        assert net.property5 is None

        try:
            len(net)
            ran = True
        except:
            ran = False
        assert ran is False

        # test Network.nodes()

        net.calculate_full()

        assert net.full is False
        assert len(net.nodes()) == 15
        assert len(net.nodes(type=Agent)) == 5
        assert len(net.nodes(type=Source)) == 5
        assert len(net.nodes(type=models.Node)) == 15
        for a in net.nodes(type=Agent):
            assert type(a) == Agent

        assert len(net.nodes(failed="all")) == 15
        assert net.nodes(failed=True) == []

        import random
        for node in random.sample(net.nodes(), 5):
            node.fail()

        assert len(net.nodes()) == 10
        assert len(net.nodes(failed=True)) == 5
        assert len(net.nodes(failed="all")) == 15
        for i in range(5):
            assert len(net.nodes(failed="all", participant_uuid=str(i)))
            assert type(net.nodes(failed="all", participant_uuid=str(i))[0]) == Agent

        # test Network.size()

        assert net.size() == 10
        assert net.size(type=Agent) in [0, 1, 2, 3, 4, 5]
        assert net.size(type=Source) in [0, 1, 2, 3, 4, 5]
        assert net.size(type=models.Node) == 10

        assert net.size(failed="all") == 15
        assert net.size(type=Agent, failed="all") == 5
        assert net.size(type=Source, failed="all") == 5
        assert net.size(type=models.Node, failed="all") == 15
        assert net.size(failed=True) == 5

        # test Network.vectors()

        assert len(net.vectors(failed="all")) == 15
        assert len(net.vectors(failed=False)) in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        assert len(net.vectors(failed=True)) in [5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
        for v in net.vectors(failed="all"):
            assert type(v) == models.Vector

        # test Network.infos()

        from wallace.information import Gene
        assert len(net.infos(origin_failed="all")) == 10
        assert len(net.infos(type=models.Info, origin_failed="all")) == 10
        assert len(net.infos(type=Gene, origin_failed="all")) == 5

        assert len(net.infos()) in [5, 6, 7, 8, 9, 10]
        assert len(net.infos(origin_failed=False)) in [5, 6, 7, 8, 9, 10]
        assert len(net.infos(type=Gene)) in [5, 4, 3, 2, 1, 0]
        assert len(net.infos(origin_failed=True)) in [0, 1, 2, 3, 4, 5]

        # test Network.transmissions()

        assert len(net.transmissions(vector_failed="all")) == 5
        assert len(net.transmissions(status="pending", vector_failed="all")) == 3
        assert len(net.transmissions(status="received", vector_failed="all")) == 2
        assert len(net.transmissions(vector_failed=True)) in [0, 1, 2, 3, 4, 5]
        assert len(net.transmissions(vector_failed=False)) in [0, 1, 2, 3, 4, 5]
        assert len(net.transmissions(vector_failed=True)) + len(net.transmissions(vector_failed=False)) == 5

        # test Network.transformations()

        assert len(net.transformations(node_failed="all")) == 2
        from wallace import transformations
        assert len(net.transformations(node_failed="all", type=transformations.Mutation)) == 0
        assert len(net.transformations(node_failed="all", type=models.Transformation)) == 2

        for t in net.transformations(node_failed="all"):
            assert type(t.node) == Agent

        # test Network.latest_transmission_recipient()

        agents = net.nodes(type=Agent, failed="all")
        from operator import attrgetter
        oldest_agent = min(agents, key=attrgetter('creation_time'))
        other_agents = [a for a in agents if a != oldest_agent]
        second_oldest_agent = min(other_agents, key=attrgetter('creation_time'))

        assert net.latest_transmission_recipient(failed="all") == second_oldest_agent

        if second_oldest_agent.failed:
            if net.latest_transmission_recipient() is not None:
                assert net.latest_transmission_recipient() != second_oldest_agent
        else:
            assert net.latest_transmission_recipient() == second_oldest_agent

        print("Testing models: Network... done!")
        sys.stdout.flush()

    ##################################################################
    # Node
    ##################################################################

    def test_create_node(self):
        """Create a basic node"""
        node = models.Node()
        self.add(node)

        assert isinstance(node.uuid, int)
        assert node.type == "base"
        assert node.creation_time
        assert len(node.infos()) == 0
        assert len(node.vectors(direction="outgoing")) == 0
        assert len(node.vectors(direction="incoming")) == 0
        assert len(node.vectors(direction="outgoing")) == 0
        assert len(node.vectors(direction="incoming")) == 0

    def test_different_node_uuids(self):
        """Test that two nodes have different uuids"""
        node1 = models.Node()
        node2 = models.Node()
        self.add(node1, node2)

        assert node1.uuid != node2.uuid

    def test_node_repr(self):
        """Test the repr of a node"""
        node = models.Node()
        self.add(node)

        assert repr(node).split("-") == ["Node", str(node.uuid), "base"]

    def _check_single_connection(self, node1, node2):

        assert node1.is_connected(direction="to", whom=node2)
        assert not node1.is_connected(direction="from", whom=node2)
        assert node2.is_connected(direction="from", whom=node1)
        assert not node2.is_connected(direction="to", whom=node2)

        vector = node1.vectors(direction="outgoing")[0]
        assert vector.origin_uuid == node1.uuid
        assert vector.destination_uuid == node2.uuid

        assert node1.vectors(direction="outgoing") == [vector]
        assert len(node1.vectors(direction="incoming")) == 0
        assert len(node2.vectors(direction="outgoing")) == 0
        assert node2.vectors(direction="incoming") == [vector]

        assert len(node1.vectors(direction="incoming")) == 0
        assert len(node1.vectors(direction="outgoing")) == 1
        assert len(node2.vectors(direction="incoming")) == 1
        assert len(node2.vectors(direction="outgoing")) == 0

        assert node1.neighbors(connection="to") == [node2]
        assert len(node1.neighbors(connection="from")) == 0
        assert node2.neighbors(connection="from") == [node1]
        assert len(node2.neighbors(connection="to")) == 0

    def test_node_connect(self):
        """Test connecting one node to another"""
        net = models.Network()
        self.db.add(net)
        self.db.commit()

        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        node3 = models.Node(network=net)
        node4 = models.Node(network=net)
        # self.add(node1, node2, node3, node4)
        # self.db.commit()

        node1.connect(whom=node2)

        assert node1.neighbors(connection="to") == [node2]

        assert node2.neighbors(connection="from") == [node1]

        node2.connect(whom=[node3, node4])

        for n in node2.neighbors(connection="to"):
            assert n in [node3, node4]
        assert node3.neighbors(connection="from") == [node2]

        assert_raises(ValueError, node1.connect, whom=node1)

        net = models.Network()
        self.add(net)

        assert_raises(TypeError, node1.connect, whom=net)

    def test_node_outdegree(self):
        node1 = models.Node()
        self.db.add(node1)

        for i in xrange(5):
            assert len(node1.vectors(direction="outgoing")) == i
            new_node = models.Node()
            self.add(new_node)
            self.db.commit()
            node1.connect(whom=new_node)
            self.add(new_node)

        assert len(node1.vectors(direction="outgoing")) == 5

        nodes = self.db.query(models.Node).all()

        node5 = [n for n in nodes if len(n.vectors(direction="outgoing")) == 5][0]
        assert node5 == node1

    def test_node_indegree(self):
        node1 = models.Node()
        self.db.add(node1)
        self.db.commit()

        for i in xrange(5):
            assert len(node1.vectors(direction="incoming")) == i
            new_node = models.Node()
            self.db.add(new_node)
            self.db.commit()
            node1.connect(direction="from", whom=new_node)
            self.add(new_node)

        assert len(node1.vectors(direction="incoming")) == 5

        nodes = self.db.query(models.Node).all()
        node5 = [n for n in nodes if len(n.vectors(direction="incoming")) == 5][0]
        assert node5 == node1

    def test_node_has_connection_to(self):
        node1 = models.Node()
        node2 = models.Node()
        self.add(node1, node2)
        self.db.commit()

        node1.connect(whom=node2)
        self.add(node1, node2)

        assert node1.is_connected(direction="to", whom=node2)
        assert not node2.is_connected(direction="to", whom=node1)

    def test_node_has_connection_from(self):
        node1 = models.Node()
        node2 = models.Node()
        self.add(node1, node2)
        self.db.commit()

        node1.connect(whom=node2)
        self.add(node1, node2)

        assert not node1.is_connected(direction="from", whom=node2)
        assert node2.is_connected(direction="from", whom=node1)

    ##################################################################
    # Vector
    ##################################################################

    def test_create_vector(self):
        """Test creating a vector between two nodes"""
        node1 = models.Node()
        node2 = models.Node()
        #vector = models.Vector(origin=node1, destination=node2)
        #self.add(node1, node2, vector)
        self.add(node1, node2)
        self.db.commit()

        node1.connect(whom=node2)

        self._check_single_connection(node1, node2)
        #assert len(vector.transmissions) == 0

    def test_kill_vector(self):
        node1 = models.Node()
        node2 = models.Node()
        vector = models.Vector(origin=node1, destination=node2)
        self.add(node1, node2, vector)

        assert vector.failed is False

        vector.fail()
        assert vector.failed is True

    def test_create_bidirectional_vectors(self):
        """Test creating a bidirectional connection between nodes"""
        node1 = models.Node()
        node2 = models.Node()
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(node1, node2, vector1, vector2)

        assert vector1.origin_uuid == node1.uuid
        assert vector1.destination_uuid == node2.uuid
        assert vector2.origin_uuid == node2.uuid
        assert vector2.destination_uuid == node1.uuid

        assert node1.vectors(direction="incoming") == [vector2]
        assert node1.vectors(direction="outgoing") == [vector1]
        assert node2.vectors(direction="incoming") == [vector1]
        assert node2.vectors(direction="outgoing") == [vector2]

        assert node1.is_connected(direction="to", whom=node2)
        assert node1.is_connected(direction="from", whom=node2)
        assert node2.is_connected(direction="to", whom=node1)
        assert node2.is_connected(direction="from", whom=node1)

        assert len(node1.vectors(direction="incoming")) == 1
        assert len(node2.vectors(direction="incoming")) == 1
        assert len(node1.vectors(direction="outgoing")) == 1
        assert len(node2.vectors(direction="outgoing")) == 1

        assert len(vector1.transmissions()) == 0
        assert len(vector2.transmissions()) == 0

    def test_vector_repr(self):
        """Test the repr of a vector"""
        node1 = models.Node()
        node2 = models.Node()
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(node1, node2, vector1, vector2)

        assert (repr(vector1).split("-") ==
                ["Vector", str(node1.uuid), str(node2.uuid)])
        assert (repr(vector2).split("-") ==
                ["Vector", str(node2.uuid), str(node1.uuid)])

    ##################################################################
    # Info
    ##################################################################

    def test_create_info(self):
        """Try creating an info"""
        node = models.Node()
        info = models.Info(origin=node, contents="foo")
        self.add(node, info)

        assert isinstance(info.uuid, int)
        assert info.type == "base"
        assert info.origin_uuid == node.uuid
        assert info.creation_time
        assert info.contents == "foo"
        assert len(info.transmissions()) == 0

        assert node.infos() == [info]

    def test_create_two_infos(self):
        """Try creating two infos"""
        node = models.Node()
        info1 = models.Info(origin=node, contents="bar")
        info2 = models.Info(origin=node, contents="foo")
        self.add(node, info1, info2)

        assert info1.uuid != info2.uuid
        assert info1.origin_uuid == info2.origin_uuid
        assert info1.creation_time != info2.creation_time
        assert info1.contents != info2.contents
        assert len(info1.transmissions()) == 0
        assert len(info2.transmissions()) == 0

        assert len(node.infos()) == 2
        assert info1 in node.infos()
        assert info2 in node.infos()

    def test_info_repr(self):
        """Check the info repr"""
        node = models.Node()
        info = models.Info(origin=node)
        self.add(info)

        assert repr(info).split("-") == ["Info", str(info.uuid), "base"]

    @raises(ValueError)
    def test_info_write_twice(self):
        """Overwrite an info's contents."""
        node = models.Node()
        info = models.Info(origin=node, contents="foo")

        self.add(node, info)

        assert info.contents == "foo"
        info.contents = "ofo"

    ##################################################################
    # Transmission
    ##################################################################

    def test_create_transmission(self):
        """Try creating a transmission"""
        node1 = models.Node()
        node2 = models.Node()
        self.add(node1, node2)
        self.db.commit()
        node1.connect(whom=node2)

        info = models.Info(origin=node1)
        node1.transmit(what=node1.infos()[0], to_whom=node2)
        #transmission = models.Transmission(info=info, destination=node2)
        #self.add(node1, node2, vector, info, transmission)

        transmission = node1.transmissions()[0]
        vector = node1.vectors()[0]

        assert isinstance(transmission.uuid, int)
        assert transmission.info_uuid == info.uuid
        assert transmission.origin_uuid == vector.origin_uuid
        assert transmission.destination_uuid == vector.destination_uuid
        assert transmission.creation_time
        assert transmission.vector == vector
        assert vector.transmissions() == [transmission]

    def test_transmission_repr(self):
        node1 = models.Node()
        node2 = models.Node()
        self.add(node1, node2)

        node1.connect(whom=node2)
        models.Info(origin=node1)

        node1.transmit(what=node1.infos()[0], to_whom=node2)
        transmission = node1.transmissions()[0]
        node1.vectors()[0]

        assert (repr(transmission).split("-") ==
                ["Transmission", str(transmission.uuid)])

    def test_node_incoming_transmissions(self):
        agent1 = nodes.ReplicatorAgent()
        agent2 = nodes.ReplicatorAgent()
        agent3 = nodes.ReplicatorAgent()
        self.add(agent1, agent2, agent3)
        self.db.commit()

        agent1.connect(direction="from", whom=[agent2, agent3])
        self.add(agent1, agent2, agent3)

        info1 = models.Info(origin=agent2, contents="foo")
        info2 = models.Info(origin=agent3, contents="bar")
        self.add(info1, info2)

        agent2.transmit(what=info1, to_whom=agent1)
        agent3.transmit(what=info2, to_whom=agent1)
        self.db.commit()

        assert len(agent1.transmissions(direction="incoming")) == 2
        assert len(agent2.transmissions(direction="incoming")) == 0
        assert len(agent3.transmissions(direction="incoming")) == 0

    def test_node_outgoing_transmissions(self):
        agent1 = nodes.ReplicatorAgent()
        agent2 = nodes.ReplicatorAgent()
        agent3 = nodes.ReplicatorAgent()
        self.add(agent1, agent2, agent3)
        self.db.commit()

        agent1.connect(whom=agent2)
        agent1.connect(whom=agent3)
        self.add(agent1, agent2, agent3)

        info1 = models.Info(origin=agent1, contents="foo")
        info2 = models.Info(origin=agent1, contents="bar")
        self.add(info1, info2)

        agent1.transmit(what=info1, to_whom=agent2)
        agent1.transmit(what=info2, to_whom=agent3)
        self.db.commit()

        assert len(agent1.transmissions(direction="outgoing")) == 2
        assert len(agent2.transmissions(direction="outgoing")) == 0
        assert len(agent3.transmissions(direction="outgoing")) == 0
