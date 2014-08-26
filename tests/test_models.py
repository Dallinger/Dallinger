from wallace import models, db
from nose.tools import raises
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm.exc import FlushError
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

    def test_create_node(self):
        node = models.Node()
        self.add(node)

        assert node.type == "base"
        assert len(node.id) == 32
        assert len(node.outgoing_vectors) == 0
        assert len(node.incoming_vectors) == 0

    def test_different_node_ids(self):
        node1 = models.Node()
        node2 = models.Node()
        self.add(node1, node2)

        assert node1.id != node2.id

    def test_node_repr(self):
        node = models.Node()
        self.add(node)

        assert repr(node).split("-") == ["Node", node.id[:6], "base"]

    def test_node_connect_to(self):
        node1 = models.Node()
        node2 = models.Node()
        node1.connect_to(node2)
        self.add(node1, node2)

        vector = node1.outgoing_vectors[0]
        assert vector.origin_id == node1.id
        assert vector.destination_id == node2.id

    def test_node_connect_from(self):
        node1 = models.Node()
        node2 = models.Node()
        node1.connect_from(node2)
        self.add(node1, node2)

        vector = node1.incoming_vectors[0]
        assert vector.origin_id == node2.id
        assert vector.destination_id == node1.id

    def test_create_vector(self):
        node1 = models.Node()
        node2 = models.Node()
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
        node1 = models.Node()
        node2 = models.Node()
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
        node1 = models.Node()
        node2 = models.Node()
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(node1, node2, vector1, vector2)

        assert repr(vector1).split("-") == ["Vector", node1.id[:6], node2.id[:6]]
        assert repr(vector2).split("-") == ["Vector", node2.id[:6], node1.id[:6]]

    @raises(IntegrityError, FlushError)
    def test_create_duplicate_vector(self):
        node1 = models.Node()
        node2 = models.Node()
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node1, destination=node2)
        self.add(node1, node2, vector1, vector2)

    def test_create_meme(self):
        meme = models.Meme(contents="foo")
        self.add(meme)

        assert meme.contents == "foo"
        assert meme.creation_time
        assert len(meme.id) == 32
        assert len(meme.transmissions) == 0

    def test_create_two_memes(self):
        meme1 = models.Meme()
        self.add(meme1)

        time.sleep(1)
        meme2 = models.Meme()
        self.add(meme2)

        assert meme1.id != meme2.id
        assert meme1.creation_time != meme2.creation_time

    def test_meme_repr(self):
        meme = models.Meme()
        self.add(meme)

        assert repr(meme).split("-") == ["Meme", meme.id[:6], "base"]

    def test_create_transmission(self):
        node1 = models.Node()
        node2 = models.Node()
        vector = models.Vector(origin=node1, destination=node2)
        meme = models.Meme()
        transmission = models.Transmission(meme=meme, vector=vector)
        self.add(node1, node2, vector, meme, transmission)

        assert transmission.meme_id == meme.id
        assert transmission.origin_id == vector.origin_id
        assert transmission.destination_id == vector.destination_id
        assert transmission.vector == vector
        assert transmission.transmit_time
        assert len(transmission.id) == 32

    def test_transmission_repr(self):
        node1 = models.Node()
        node2 = models.Node()
        vector = models.Vector(origin=node1, destination=node2)
        meme = models.Meme()
        transmission = models.Transmission(meme=meme, vector=vector)
        self.add(node1, node2, vector, meme, transmission)

        assert repr(transmission).split("-") == ["Transmission", transmission.id[:6]]

    def test_node_transmit(self):
        node1 = models.Node()
        node2 = models.Node()
        node1.connect_to(node2)
        meme = models.Meme(contents="foo")
        self.add(node1, node2, meme)

        node1.transmit(meme, node2)
        self.db.commit()

        transmission = node1.outgoing_transmissions[0]
        assert transmission.meme_id == meme.id
        assert transmission.origin_id == node1.id
        assert transmission.destination_id == node2.id

    @raises(ValueError)
    def test_node_transmit_no_connection(self):
        node1 = models.Node()
        node2 = models.Node()
        meme = models.Meme(contents="foo")
        self.add(node1, node2, meme)

        node1.transmit(meme, node2)
        self.db.commit()

    def test_node_broadcast(self):
        node1 = models.Node()
        self.db.add(node1)

        for i in xrange(5):
            new_node = models.Node()
            node1.connect_to(new_node)
            self.db.add(new_node)

        meme = models.Meme(contents="foo")
        self.add(meme)

        node1.broadcast(meme)
        self.db.commit()

        transmissions = node1.outgoing_transmissions
        assert len(transmissions) == 5

    def test_node_outdegree(self):
        node1 = models.Node()
        self.db.add(node1)

        for i in xrange(5):
            assert node1.outdegree == i
            new_node = models.Node()
            node1.connect_to(new_node)
            self.add(new_node)

        assert node1.outdegree == 5

    def test_node_indegree(self):
        node1 = models.Node()
        self.db.add(node1)

        for i in xrange(5):
            assert node1.indegree == i
            new_node = models.Node()
            node1.connect_from(new_node)
            self.add(new_node)

        assert node1.indegree == 5

    def test_node_has_connection_to(self):
        node1 = models.Node()
        node2 = models.Node()
        node1.connect_to(node2)
        self.add(node1, node2)

        assert node1.has_connection_to(node2)
        assert not node2.has_connection_to(node1)

    def test_node_has_connection_from(self):
        node1 = models.Node()
        node2 = models.Node()
        node1.connect_to(node2)
        self.add(node1, node2)

        assert not node1.has_connection_from(node2)
        assert node2.has_connection_from(node1)

    def test_node_incoming_transmissions(self):
        node1 = models.Node()
        node2 = models.Node()
        node3 = models.Node()
        node1.connect_from(node2)
        node1.connect_from(node3)
        self.add(node1, node2, node3)

        meme1 = models.Meme(contents="foo")
        meme2 = models.Meme(contents="bar")
        self.add(meme1, meme2)

        node2.transmit(meme1, node1)
        node3.transmit(meme2, node1)
        self.db.commit()

        assert len(node1.incoming_transmissions) == 2
        assert len(node2.incoming_transmissions) == 0
        assert len(node3.incoming_transmissions) == 0

    def test_node_outgoing_transmissions(self):
        node1 = models.Node()
        node2 = models.Node()
        node3 = models.Node()
        node1.connect_to(node2)
        node1.connect_to(node3)
        self.add(node1, node2, node3)

        meme1 = models.Meme(contents="foo")
        meme2 = models.Meme(contents="bar")
        self.add(meme1, meme2)

        node1.transmit(meme1, node2)
        node1.transmit(meme2, node3)
        self.db.commit()

        assert len(node1.outgoing_transmissions) == 2
        assert len(node2.outgoing_transmissions) == 0
        assert len(node3.outgoing_transmissions) == 0
