from wallace import models, information, db


class TestInformation(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_genome(self):
        node = models.Node()
        info = information.Genome(origin=node)
        self.add(node, info)

        assert info.type == "genome"
        assert info.contents is None

    def test_create_memome(self):
        node = models.Node()
        info = information.Memome(origin=node)
        self.add(node, info)

        assert info.type == "memome"
        assert info.contents is None
