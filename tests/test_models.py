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
        """Test networks."""
        print("")
        print("Testing models: Network...", end="\r")
        sys.stdout.flush()

        # create test network:

        net = models.Network()
        self.db.add(net)
        self.db.commit()

        net = models.Network.query.one()

        assert repr(net) == "<Network-1-network with 0 nodes, 0 vectors, 0 infos, 0 transmissions and 0 transformations>"

        from wallace.nodes import Agent, Source

        for i in range(5):

            participant = models.Participant(worker_id=str(i), hit_id=str(i), assignment_id=str(i), mode="test")
            self.db.add(participant)
            self.db.commit()

            # nodes
            node = models.Node(network=net)
            agent = Agent(network=net, participant=participant)
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

        assert repr(net) == "<Network-1-network with 15 nodes, 15 vectors, 10 infos, 5 transmissions and 2 transformations>"

        # Test Network sql columns

        assert isinstance(net.id, int)
        assert net.id == 1
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
            assert len(net.nodes(failed="all", participant_id=i+1)) == 1
            assert type(net.nodes(failed="all", participant_id=i+1)[0]) == Agent

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
        assert len(net.infos(failed="all")) == 10
        assert len(net.infos(type=models.Info, failed="all")) == 10
        assert len(net.infos(type=Gene, failed="all")) == 5

        assert len(net.infos()) in [5, 6, 7, 8, 9, 10]
        assert len(net.infos(failed=False)) in [5, 6, 7, 8, 9, 10]
        assert len(net.infos(type=Gene)) in [5, 4, 3, 2, 1, 0]
        assert len(net.infos(failed=True)) in [0, 1, 2, 3, 4, 5]

        # test Network.transmissions()

        assert len(net.transmissions(failed="all")) == 5
        assert len(net.transmissions(status="pending", failed="all")) == 3
        assert len(net.transmissions(status="received", failed="all")) == 2
        assert len(net.transmissions(failed=True)) in [0, 1, 2, 3, 4, 5]
        assert len(net.transmissions(failed=False)) in [0, 1, 2, 3, 4, 5]
        assert len(net.transmissions(failed=True)) + len(net.transmissions(failed=False)) == 5

        # test Network.transformations()

        assert len(net.transformations(failed="all")) == 2
        from wallace import transformations
        assert len(net.transformations(failed="all", type=transformations.Mutation)) == 0
        assert len(net.transformations(failed="all", type=models.Transformation)) == 2

        for t in net.transformations(failed="all"):
            assert type(t.node) == Agent

        print("Testing models: Network... done!")
        sys.stdout.flush()

    ##################################################################
    # Node
    ##################################################################

    def test_create_node(self):
        """Create a basic node"""
        net = models.Network()
        self.db.add(net)
        node = models.Node(network=net)
        self.add(node)

        assert isinstance(node.id, int)
        assert node.type == "node"
        assert node.creation_time
        assert len(node.infos()) == 0
        assert len(node.vectors(direction="outgoing")) == 0
        assert len(node.vectors(direction="incoming")) == 0
        assert len(node.vectors(direction="outgoing")) == 0
        assert len(node.vectors(direction="incoming")) == 0

    def test_different_node_ids(self):
        """Test that two nodes have different ids"""
        net = models.Network()
        self.db.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(node1, node2)

        assert node1.id != node2.id

    def test_node_repr(self):
        """Test the repr of a node"""
        net = models.Network()
        self.db.add(net)
        node = models.Node(network=net)
        self.add(node)

        assert repr(node).split("-") == ["Node", str(node.id), "node"]

    def _check_single_connection(self, node1, node2):

        assert node1.is_connected(direction="to", whom=node2)
        assert not node1.is_connected(direction="from", whom=node2)
        assert node2.is_connected(direction="from", whom=node1)
        assert not node2.is_connected(direction="to", whom=node2)

        vector = node1.vectors(direction="outgoing")[0]
        assert vector.origin_id == node1.id
        assert vector.destination_id == node2.id

        assert node1.vectors(direction="outgoing") == [vector]
        assert len(node1.vectors(direction="incoming")) == 0
        assert len(node2.vectors(direction="outgoing")) == 0
        assert node2.vectors(direction="incoming") == [vector]

        assert len(node1.vectors(direction="incoming")) == 0
        assert len(node1.vectors(direction="outgoing")) == 1
        assert len(node2.vectors(direction="incoming")) == 1
        assert len(node2.vectors(direction="outgoing")) == 0

        assert node1.neighbors(direction="to") == [node2]
        assert len(node1.neighbors(direction="from")) == 0
        assert node2.neighbors(direction="from") == [node1]
        assert len(node2.neighbors(direction="to")) == 0

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

        assert node1.neighbors(direction="to") == [node2]

        assert node2.neighbors(direction="from") == [node1]

        node2.connect(whom=[node3, node4])

        for n in node2.neighbors(direction="to"):
            assert n in [node3, node4]
        assert node3.neighbors(direction="from") == [node2]

        assert_raises(ValueError, node1.connect, whom=node1)

        net = models.Network()
        self.add(net)

        assert_raises(TypeError, node1.connect, whom=net)

    def test_node_outdegree(self):
        net = models.Network()
        self.add(net)
        node1 = models.Node(network=net)
        self.db.add(node1)

        for i in xrange(5):
            assert len(node1.vectors(direction="outgoing")) == i
            new_node = models.Node(network=net)
            self.add(new_node)
            self.db.commit()
            node1.connect(whom=new_node)
            self.add(new_node)

        assert len(node1.vectors(direction="outgoing")) == 5

        nodes = self.db.query(models.Node).all()

        node5 = [n for n in nodes if len(n.vectors(direction="outgoing")) == 5][0]
        assert node5 == node1

    def test_node_indegree(self):
        net = models.Network()
        self.add(net)
        node1 = models.Node(network=net)
        self.db.add(node1)
        self.db.commit()

        for i in xrange(5):
            assert len(node1.vectors(direction="incoming")) == i
            new_node = models.Node(network=net)
            self.db.add(new_node)
            self.db.commit()
            node1.connect(direction="from", whom=new_node)
            self.add(new_node)

        assert len(node1.vectors(direction="incoming")) == 5

        nodes = self.db.query(models.Node).all()
        node5 = [n for n in nodes if len(n.vectors(direction="incoming")) == 5][0]
        assert node5 == node1

    def test_node_has_connection_to(self):
        net = models.Network()
        self.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(node1, node2)
        self.db.commit()

        node1.connect(whom=node2)
        self.add(node1, node2)

        assert node1.is_connected(direction="to", whom=node2)
        assert not node2.is_connected(direction="to", whom=node1)

    def test_node_has_connection_from(self):
        net = models.Network()
        self.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
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
        net = models.Network()
        self.db.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        #vector = models.Vector(origin=node1, destination=node2)
        #self.add(node1, node2, vector)
        self.add(node1, node2)
        self.db.commit()

        node1.connect(whom=node2)

        self._check_single_connection(node1, node2)
        #assert len(vector.transmissions) == 0

    def test_kill_vector(self):
        net = models.Network()
        self.db.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        vector = models.Vector(origin=node1, destination=node2)
        self.add(node1, node2, vector)

        assert vector.failed is False

        vector.fail()
        assert vector.failed is True

    def test_create_bidirectional_vectors(self):
        """Test creating a bidirectional connection between nodes"""
        net = models.Network()
        self.db.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(node1, node2, vector1, vector2)

        assert vector1.origin_id == node1.id
        assert vector1.destination_id == node2.id
        assert vector2.origin_id == node2.id
        assert vector2.destination_id == node1.id

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
        net = models.Network()
        self.db.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(node1, node2, vector1, vector2)

        assert (repr(vector1).split("-") ==
                ["Vector", str(node1.id), str(node2.id)])
        assert (repr(vector2).split("-") ==
                ["Vector", str(node2.id), str(node1.id)])

    ##################################################################
    # Info
    ##################################################################

    def test_create_info(self):
        """Try creating an info"""
        net = models.Network()
        self.db.add(net)
        node = models.Node(network=net)
        info = models.Info(origin=node, contents="foo")
        self.add(node, info)

        assert isinstance(info.id, int)
        assert info.type == "info"
        assert info.origin_id == node.id
        assert info.creation_time
        assert info.contents == "foo"
        assert len(info.transmissions()) == 0

        assert node.infos() == [info]

    def test_create_two_infos(self):
        """Try creating two infos"""
        net = models.Network()
        self.db.add(net)
        node = models.Node(network=net)
        info1 = models.Info(origin=node, contents="bar")
        info2 = models.Info(origin=node, contents="foo")
        self.add(node, info1, info2)

        assert info1.id != info2.id
        assert info1.origin_id == info2.origin_id
        assert info1.creation_time != info2.creation_time
        assert info1.contents != info2.contents
        assert len(info1.transmissions()) == 0
        assert len(info2.transmissions()) == 0

        assert len(node.infos()) == 2
        assert info1 in node.infos()
        assert info2 in node.infos()

    def test_info_repr(self):
        """Check the info repr"""
        net = models.Network()
        self.db.add(net)
        node = models.Node(network=net)
        info = models.Info(origin=node)
        self.add(info)

        assert repr(info).split("-") == ["Info", str(info.id), "info"]

    @raises(ValueError)
    def test_info_write_twice(self):
        """Overwrite an info's contents."""
        net = models.Network()
        self.db.add(net)
        node = models.Node(network=net)
        info = models.Info(origin=node, contents="foo")

        self.add(node, info)

        assert info.contents == "foo"
        info.contents = "ofo"

    ##################################################################
    # Transmission
    ##################################################################

    def test_create_transmission(self):
        """Try creating a transmission"""
        net = models.Network()
        self.db.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(node1, node2)
        self.db.commit()
        node1.connect(whom=node2)

        info = models.Info(origin=node1)
        node1.transmit(what=node1.infos()[0], to_whom=node2)
        #transmission = models.Transmission(info=info, destination=node2)
        #self.add(node1, node2, vector, info, transmission)

        transmission = node1.transmissions()[0]
        vector = node1.vectors()[0]

        assert isinstance(transmission.id, int)
        assert transmission.info_id == info.id
        assert transmission.origin_id == vector.origin_id
        assert transmission.destination_id == vector.destination_id
        assert transmission.creation_time
        assert transmission.vector == vector
        assert vector.transmissions() == [transmission]

    def test_transmission_repr(self):
        net = models.Network()
        self.db.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(node1, node2)

        node1.connect(whom=node2)
        models.Info(origin=node1)

        node1.transmit(what=node1.infos()[0], to_whom=node2)
        transmission = node1.transmissions()[0]
        node1.vectors()[0]

        assert (repr(transmission).split("-") ==
                ["Transmission", str(transmission.id)])

    def test_node_incoming_transmissions(self):
        net = models.Network()
        self.db.add(net)
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)
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
        net = models.Network()
        self.db.add(net)
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)
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

    def test_property_node(self):
        net = models.Network()
        self.db.add(net)
        node = models.Node(network=net)
        node.property1 = "foo"
        self.add(node)

        assert node.property1 == "foo"

    def test_creation_time(self):
        net = models.Network()
        self.db.add(net)
        node = models.Node(network=net)
        self.add(node)
        assert node.creation_time is not None
