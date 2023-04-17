from dallinger import models, nodes


class TestSources(object):
    def add(self, session, *args):
        session.add_all(args)
        session.commit()

    def test_create_random_binary_string_source(self, db_session):
        net = models.Network()
        self.add(db_session, net)
        source = nodes.RandomBinaryStringSource(network=net)
        self.add(db_session, source)

        assert source

    def test_transmit_random_binary_string_source(self, db_session):
        net = models.Network()
        self.add(db_session, net)
        source = nodes.RandomBinaryStringSource(network=net)
        agent = nodes.ReplicatorAgent(network=net)
        db_session.add(source)
        db_session.add(agent)
        db_session.commit()

        source.connect(whom=agent)
        self.add(db_session, source, agent)

        source.transmit(to_whom=agent)
        db_session.commit()

        agent.receive()
        db_session.commit()

        assert agent.infos()[0].contents in ["00", "01", "10", "11"]

    def test_broadcast_random_binary_string_source(self, db_session):
        net = models.Network()
        self.add(db_session, net)
        source = nodes.RandomBinaryStringSource(network=net)
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        db_session.add(agent1)
        db_session.add(agent2)
        db_session.commit()
        source.connect(whom=agent1)
        source.connect(whom=agent2)
        self.add(db_session, source, agent1, agent2)

        source.transmit(what=source.create_information())
        db_session.commit()

        agent1.receive()
        agent2.receive()
        db_session.commit()

        assert agent1.infos()[0].contents in ["00", "01", "10", "11"]
        assert agent2.infos()[0].contents in ["00", "01", "10", "11"]
