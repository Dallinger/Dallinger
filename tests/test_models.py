from wallace import models, db
from nose.tools import raises
from sqlalchemy.exc import DataError, IntegrityError, OperationalError
from sqlalchemy.orm.exc import FlushError
from datetime import datetime
import time


class TestModels(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_source_node(self):
        node = models.Node(type="source")
        self.add(node)

        assert node.type == "source"
        assert len(node.id) == 32
        assert len(node.outgoing_vectors) == 0
        assert len(node.incoming_vectors) == 0
        assert len(node.outgoing_memes) == 0

    def test_create_agent_node(self):
        node = models.Node(type="agent")
        self.add(node)

        assert node.type == "agent"
        assert len(node.id) == 32
        assert len(node.outgoing_vectors) == 0
        assert len(node.incoming_vectors) == 0
        assert len(node.outgoing_memes) == 0

    def test_create_filter_node(self):
        node = models.Node(type="filter")
        self.add(node)

        assert node.type == "filter"
        assert len(node.id) == 32
        assert len(node.outgoing_vectors) == 0
        assert len(node.incoming_vectors) == 0
        assert len(node.outgoing_memes) == 0

    def test_different_node_ids(self):
        node1 = models.Node(type="source")
        node2 = models.Node(type="source")
        self.add(node1, node2)

        assert node1.id != node2.id

    @raises(DataError)
    def test_create_invalid_node(self):
        node = models.Node(type="bar")
        self.add(node)

    def test_node_repr(self):
        node1 = models.Node(type="source")
        node2 = models.Node(type="agent")
        node3 = models.Node(type="filter")
        self.add(node1, node2, node3)

        assert repr(node1).split("-") == ["Node", node1.id[:6], "source"]
        assert repr(node2).split("-") == ["Node", node2.id[:6], "agent"]
        assert repr(node3).split("-") == ["Node", node3.id[:6], "filter"]

    def test_node_connect_to(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = node1.connect_to(node2)
        self.add(node1, node2, vector)

        assert vector.origin_id == node1.id
        assert vector.destination_id == node2.id

    def test_node_connect_from(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = node1.connect_from(node2)
        self.add(node1, node2, vector)

        assert vector.origin_id == node2.id
        assert vector.destination_id == node1.id

    def test_create_vector(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = models.Vector(origin=node1, destination=node2)
        self.add(node1, node2, vector)

        # check that the origin/destination ids are correct
        assert vector.origin_id == node1.id
        assert vector.destination_id == node2.id
        assert len(vector.transmissions) == 0

        # check that incoming/outgoing vectors are correct
        assert len(node1.incoming_vectors) == 0
        assert node1.outgoing_vectors == [vector]
        assert node2.incoming_vectors == [vector]
        assert len(node2.outgoing_vectors) == 0

    def test_create_bidirectional_vectors(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(node1, node2, vector1, vector2)

        # check that the origin/destination ids are correct
        assert vector1.origin_id == node1.id
        assert vector1.destination_id == node2.id
        assert len(vector1.transmissions) == 0
        assert vector2.origin_id == node2.id
        assert vector2.destination_id == node1.id
        assert len(vector2.transmissions) == 0

        # check that incoming/outgoing vectors are correct
        assert node1.incoming_vectors == [vector2]
        assert node1.outgoing_vectors == [vector1]
        assert node2.incoming_vectors == [vector1]
        assert node2.outgoing_vectors == [vector2]

    def test_vector_repr(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(node1, node2, vector1, vector2)

        assert repr(vector1).split("-") == ["Vector", node1.id[:6], node2.id[:6]]
        assert repr(vector2).split("-") == ["Vector", node2.id[:6], node1.id[:6]]

    @raises(IntegrityError, FlushError)
    def test_create_duplicate_vector(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node1, destination=node2)
        self.add(node1, node2, vector1, vector2)

    def test_create_meme(self):
        node = models.Node(type="agent")
        meme = models.Meme(origin=node, contents="foo")
        self.add(node, meme)

        assert meme.contents == "foo"
        assert meme.creation_time
        assert meme.origin_id == node.id
        assert node.outgoing_memes == [meme]
        assert len(meme.id) == 32
        assert len(meme.transmissions) == 0

    def test_create_two_memes(self):
        node = models.Node(type="agent")
        meme1 = models.Meme(origin=node)
        self.add(node, meme1)

        time.sleep(1)
        meme2 = models.Meme(origin=node)
        self.add(meme2)

        assert meme1.id != meme2.id
        assert meme1.creation_time != meme2.creation_time

    @raises(OperationalError)
    def test_create_orphan_meme(self):
        self.add(models.Meme())

    def test_meme_repr(self):
        node = models.Node(type="agent")
        meme = models.Meme(origin=node)
        self.add(node, meme)

        assert repr(meme).split("-") == ["Meme", meme.id[:6]]

    def test_create_transmission(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = models.Vector(origin=node1, destination=node2)
        meme = models.Meme(origin=node1)
        transmission = models.Transmission(meme=meme, vector=vector)
        self.add(node1, node2, vector, meme, transmission)

        assert transmission.meme_id == meme.id
        assert transmission.origin_id == meme.origin_id
        assert transmission.origin_id == vector.origin_id
        assert transmission.destination_id == vector.destination_id
        assert transmission.vector == vector
        assert transmission.transmit_time
        assert len(transmission.id) == 32

    def test_transmission_repr(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = models.Vector(origin=node1, destination=node2)
        meme = models.Meme(origin=node1)
        transmission = models.Transmission(meme=meme, vector=vector)
        self.add(node1, node2, vector, meme, transmission)

        assert repr(transmission).split("-") == ["Transmission", transmission.id[:6]]

    def test_node_create_empty_meme(self):
        node = models.Node(type="agent")
        meme = node.create_meme()
        self.add(node, meme)

        assert meme.origin_id == node.id
        assert meme.contents is None

    def test_node_create_meme(self):
        node = models.Node(type="agent")
        meme = node.create_meme(contents="foo")
        self.add(node, meme)

        assert meme.origin_id == node.id
        assert meme.contents == "foo"

    def test_node_transmit(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = node1.connect_to(node2)
        meme = node1.create_meme(contents="foo")
        self.add(node1, node2, vector, meme)

        transmission = node1.transmit(meme, node2)
        self.add(transmission)

        assert transmission.meme_id == meme.id
        assert transmission.origin_id == node1.id
        assert transmission.destination_id == node2.id

    @raises(ValueError)
    def test_node_transmit_bad_origin(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = node1.connect_to(node2)
        meme = node2.create_meme(contents="foo")
        self.add(node1, node2, vector, meme)

        transmission = node1.transmit(meme, node2)
        self.add(transmission)

    @raises(ValueError)
    def test_node_transmit_no_connection(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        meme = node1.create_meme(contents="foo")
        self.add(node1, node2, meme)

        transmission = node1.transmit(meme, node2)
        self.add(transmission)

    def test_node_broadcast(self):
        node1 = models.Node(type="agent")
        self.db.add(node1)

        for i in xrange(5):
            new_node = models.Node(type="agent")
            vector = node1.connect_to(new_node)
            self.db.add_all([new_node, vector])

        meme = node1.create_meme("foo")
        self.add(meme)

        transmissions = node1.broadcast(meme)
        self.add(*transmissions)

        assert len(transmissions) == 5

    def test_node_outdegree(self):
        node1 = models.Node(type="agent")
        self.db.add(node1)

        for i in xrange(5):
            assert node1.outdegree == i
            new_node = models.Node(type="agent")
            vector = node1.connect_to(new_node)
            self.add(new_node, vector)

        assert node1.outdegree == 5

    def test_node_indegree(self):
        node1 = models.Node(type="agent")
        self.db.add(node1)

        for i in xrange(5):
            assert node1.indegree == i
            new_node = models.Node(type="agent")
            vector = node1.connect_from(new_node)
            self.add(new_node, vector)

        assert node1.indegree == 5

    def test_node_has_connection_to(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = node1.connect_to(node2)
        self.add(node1, node2, vector)

        assert node1.has_connection_to(node2)
        assert not node2.has_connection_to(node1)

    def test_node_has_connection_from(self):
        node1 = models.Node(type="agent")
        node2 = models.Node(type="agent")
        vector = node1.connect_to(node2)
        self.add(node1, node2, vector)

        assert not node1.has_connection_from(node2)
        assert node2.has_connection_from(node1)
