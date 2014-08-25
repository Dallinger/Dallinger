from wallace import models, db
from nose.tools import raises
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm.exc import FlushError
from datetime import datetime


class TestModels(object):

    def setup(self):
        db.db.rollback()
        self.db = db.init_db(drop_all=True)

    def add(self, node):
        self.db.add(node)
        self.db.commit()
        return node

    def test_create_source_node(self):
        node = self.add(models.Node(type="source"))
        assert node.type == "source"
        assert len(node.id) == 32
        assert len(node.outgoing_vectors) == 0
        assert len(node.incoming_vectors) == 0
        assert len(node.outgoing_memes) == 0

    def test_create_participant_node(self):
        node = self.add(models.Node(type="participant"))
        assert node.type == "participant"
        assert len(node.id) == 32
        assert len(node.outgoing_vectors) == 0
        assert len(node.incoming_vectors) == 0
        assert len(node.outgoing_memes) == 0

    def test_create_filter_node(self):
        node = self.add(models.Node(type="filter"))
        assert node.type == "filter"
        assert len(node.id) == 32
        assert len(node.outgoing_vectors) == 0
        assert len(node.incoming_vectors) == 0
        assert len(node.outgoing_memes) == 0

    def test_different_node_ids(self):
        node1 = self.add(models.Node(type="source"))
        node2 = self.add(models.Node(type="source"))
        assert node1.id != node2.id

    @raises(IntegrityError)
    def test_create_invalid_node(self):
        self.add(models.Node(type="bar"))

    def test_node_repr(self):
        node = self.add(models.Node(type="source"))
        assert repr(node).split("-") == ["Node", node.id[:6], "source"]

        node = self.add(models.Node(type="participant"))
        assert repr(node).split("-") == ["Node", node.id[:6], "participant"]

        node = self.add(models.Node(type="filter"))
        assert repr(node).split("-") == ["Node", node.id[:6], "filter"]

    def test_create_vector(self):
        node1 = self.add(models.Node(type="participant"))
        node2 = self.add(models.Node(type="participant"))
        vector = self.add(models.Vector(origin=node1, destination=node2))

        # check that the origin/destination ids are correct
        assert vector.origin_id == node1.id
        assert vector.destination_id == node2.id

        # check that incoming/outgoing vectors are correct
        assert node1.incoming_vectors == []
        assert node1.outgoing_vectors == [vector]
        assert node2.incoming_vectors == [vector]
        assert node2.outgoing_vectors == []

    def test_create_bidirectional_vectors(self):
        node1 = self.add(models.Node(type="participant"))
        node2 = self.add(models.Node(type="participant"))
        vector1 = self.add(models.Vector(origin=node1, destination=node2))
        vector2 = self.add(models.Vector(origin=node2, destination=node1))

        # check that the origin/destination ids are correct
        assert vector1.origin_id == node1.id
        assert vector1.destination_id == node2.id
        assert vector2.origin_id == node2.id
        assert vector2.destination_id == node1.id

        # check that incoming/outgoing vectors are correct
        assert node1.incoming_vectors == [vector2]
        assert node1.outgoing_vectors == [vector1]
        assert node2.incoming_vectors == [vector1]
        assert node2.outgoing_vectors == [vector2]

    def test_vector_repr(self):
        node1 = self.add(models.Node(type="participant"))
        node2 = self.add(models.Node(type="participant"))
        vector1 = self.add(models.Vector(origin=node1, destination=node2))
        vector2 = self.add(models.Vector(origin=node2, destination=node1))

        assert repr(vector1).split("-") == ["Vector", node1.id[:6], node2.id[:6]]
        assert repr(vector2).split("-") == ["Vector", node2.id[:6], node1.id[:6]]

    @raises(IntegrityError, FlushError)
    def test_create_duplicate_vector(self):
        node1 = self.add(models.Node(type="participant"))
        node2 = self.add(models.Node(type="participant"))
        self.add(models.Vector(origin=node1, destination=node2))
        self.add(models.Vector(origin=node1, destination=node2))

    def test_create_meme(self):
        node = self.add(models.Node(type="participant"))

        before = datetime.now()
        meme = self.add(models.Meme(origin=node, contents="foo"))
        after = datetime.now()

        assert meme.contents == "foo"
        assert meme.creation_time > before
        assert meme.creation_time < after
        assert meme.origin_id == node.id
        assert len(meme.id) == 32

    def test_create_empty_meme(self):
        node = self.add(models.Node(type="participant"))

        before = datetime.now()
        meme = self.add(models.Meme(origin=node))
        after = datetime.now()

        assert meme.contents is None
        assert meme.creation_time > before
        assert meme.creation_time < after
        assert meme.origin_id == node.id
        assert node.outgoing_memes == [meme]
        assert len(meme.id) == 32

    def test_create_two_memes(self):
        node = self.add(models.Node(type="participant"))
        meme1 = self.add(models.Meme(origin=node))
        meme2 = self.add(models.Meme(origin=node))
        assert meme1.id != meme2.id
        assert meme1.creation_time != meme2.creation_time

    @raises(IntegrityError)
    def test_create_orphan_meme(self):
        self.add(models.Meme())

    def test_meme_repr(self):
        node = self.add(models.Node(type="participant"))
        meme = self.add(models.Meme(origin=node))
        assert repr(meme).split("-") == ["Meme", meme.id[:6]]
