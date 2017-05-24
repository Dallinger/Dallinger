from dallinger import nodes, db, information, models


class TestEnvironments(object):

    def setup(self):
        """Set up the environment by resetting the tables."""
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_environment(self):
        """Create an environment"""
        net = models.Network()
        self.db.add(net)
        environment = nodes.Environment(network=net)
        information.State(origin=environment, contents="foo")
        self.db.commit()

        assert isinstance(environment.id, int)
        assert environment.type == "environment"
        assert environment.creation_time
        assert environment.state().contents == "foo"

    def test_create_environment_get_observed(self):
        net = models.Network()
        self.db.add(net)
        environment = nodes.Environment(network=net)
        information.State(origin=environment, contents="foo")

        agent = nodes.ReplicatorAgent(network=net)

        environment.connect(direction="to", whom=agent)
        environment.transmit(to_whom=agent)
        agent.receive()

        assert agent.infos()[0].contents == "foo"

    def test_environment_update(self):
        net = models.Network()
        self.db.add(net)
        environment = nodes.Environment(network=net)
        environment.update("some content")
        self.db.commit()

        state = environment.state()

        assert state.contents == u'some content'
