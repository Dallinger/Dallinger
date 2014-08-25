from wallace import models, db
from nose.tools import raises
from sqlalchemy.exc import IntegrityError


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

    def test_create_participant_node(self):
        node = self.add(models.Node(type="participant"))
        assert node.type == "participant"
        assert len(node.id) == 32

    def test_create_filter_node(self):
        node = self.add(models.Node(type="filter"))
        assert node.type == "filter"
        assert len(node.id) == 32

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
