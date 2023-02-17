from dallinger import information, models, nodes


class TestEnvironments(object):
    def test_create_environment(self, db_session):
        """Create an environment"""
        net = models.Network()
        db_session.add(net)
        environment = nodes.Environment(network=net)
        db_session.commit()
        assert isinstance(environment.id, int)
        assert environment.type == "environment"
        assert environment.creation_time
        assert environment.state() is None

        information.State(origin=environment, contents="foo")
        db_session.commit()

        assert environment.state().contents == "foo"

    def test_create_environment_get_observed(self, db_session):
        net = models.Network()
        db_session.add(net)
        environment = nodes.Environment(network=net)
        information.State(origin=environment, contents="foo")

        agent = nodes.ReplicatorAgent(network=net)

        environment.connect(direction="to", whom=agent)
        environment.transmit(to_whom=agent)
        agent.receive()

        assert agent.infos()[0].contents == "foo"

    def test_environment_update(self, db_session):
        net = models.Network()
        db_session.add(net)
        environment = nodes.Environment(network=net)
        environment.update("some content")
        db_session.commit()

        state = environment.state()

        assert state.contents == "some content"
