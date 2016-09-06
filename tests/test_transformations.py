from dallinger import db, models


class TestTransformations(object):

    def setup(self):
        """Set up the environment by resetting the tables."""
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_identity_transformation(self):
        net = models.Network()
        self.add(net)
        node = models.Node(network=net)
        self.db.add(node)
        self.db.commit()

        info_in = models.Info(origin=node, contents="foo")
        self.db.add(info_in)
        self.db.commit()

        node.replicate(info_in)

        # # Create a new info based on the old one.
        # info_out = models.Info(origin=node, contents=info_in.contents)
        # self.db.add(info_in)
        # self.db.commit()

        # # Register the transformation.
        # transformation = transformations.Replication(
        #     info_out=info_out,
        #     info_in=info_in)

        # self.db.add(transformation)
        # self.db.commit()

        assert node.infos()[-1].contents == "foo"
        assert len(node.infos()) == 2

    # def test_shuffle_transformation(self):
    #     node = models.Node()
    #     self.db.add(node)
    #     self.db.commit()

    #     info_in = models.Info(origin=node, contents="foo")
    #     self.db.add(info_in)
    #     self.db.commit()

    #     # Create a new info based on the old one.
    #     shuffled_string = ''.join(
    #         random.sample(info_in.contents, len(info_in.contents)))

    #     info_out = models.Info(origin=node, contents=shuffled_string)

    #     # Register the transformation.
    #     transformation = transformations.Transformation(
    #         info_out=info_out,
    #         info_in=info_in)

    #     self.db.add(transformation)
    #     self.db.commit()

    #     assert info_out.contents in ["foo", "ofo", "oof"]
