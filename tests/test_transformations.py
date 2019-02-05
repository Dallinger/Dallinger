from dallinger import models


class TestTransformations(object):
    def test_identity_transformation(self, db_session):
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        db_session.add(node)
        db_session.commit()

        info_in = models.Info(origin=node, contents="foo")
        db_session.add(info_in)
        db_session.commit()

        node.replicate(info_in)

        # # Create a new info based on the old one.
        # info_out = models.Info(origin=node, contents=info_in.contents)
        # db_session.add(info_in)
        # db_session.commit()

        # # Register the transformation.
        # transformation = transformations.Replication(
        #     info_out=info_out,
        #     info_in=info_in)

        # db_session.add(transformation)
        # db_session.commit()

        assert node.infos()[-1].contents == "foo"
        assert len(node.infos()) == 2

    # def test_shuffle_transformation(self):
    #     node = models.Node()
    #     db_session.add(node)
    #     db_session.commit()

    #     info_in = models.Info(origin=node, contents="foo")
    #     db_session.add(info_in)
    #     db_session.commit()

    #     # Create a new info based on the old one.
    #     shuffled_string = ''.join(
    #         random.sample(info_in.contents, len(info_in.contents)))

    #     info_out = models.Info(origin=node, contents=shuffled_string)

    #     # Register the transformation.
    #     transformation = transformations.Transformation(
    #         info_out=info_out,
    #         info_in=info_in)

    #     db_session.add(transformation)
    #     db_session.commit()

    #     assert info_out.contents in ["foo", "ofo", "oof"]
