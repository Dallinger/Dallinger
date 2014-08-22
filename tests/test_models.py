from wallace import models, db
from nose.tools import raises


class TestModels(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def test_create_source_node(self):
        node = models.Node("foo", "source")
        self.db.add(node)
        self.db.commit()
        assert node.name == "foo"
        assert node.type == "source"
        assert len(node.id) == 32

    def test_create_participant_node(self):
        node = models.Node("foo", "participant")
        self.db.add(node)
        self.db.commit()
        assert node.name == "foo"
        assert node.type == "participant"
        assert len(node.id) == 32

    def test_create_filter_node(self):
        node = models.Node("foo", "filter")
        self.db.add(node)
        self.db.commit()
        assert node.name == "foo"
        assert node.type == "filter"
        assert len(node.id) == 32

    def test_different_node_ids(self):
        node1 = models.Node("foo", "source")
        node2 = models.Node("bar", "source")
        self.db.add(node1)
        self.db.add(node2)
        self.db.commit()
        assert node1.id != node2.id

    @raises(ValueError)
    def test_create_invalid_node(self):
        models.Node("foo", "bar")

    @raises(ValueError)
    def test_create_node_with_null_name(self):
        models.Node(None, "source")
