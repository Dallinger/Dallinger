from dallinger import information, models


class TestInformation(object):
    def test_create_genome(self, db_session):
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        info = information.Gene(origin=node)
        db_session.commit()

        assert info.type == "gene"
        assert info.contents is None

    def test_create_memome(self, db_session):
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        info = information.Meme(origin=node)
        db_session.commit()

        assert info.type == "meme"
        assert info.contents is None
