from wallace import nodes, db, information


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
        environment = nodes.Environment()
        state = information.State(origin=environment, contents="foo")
        self.add(environment, state)

        assert isinstance(environment.uuid, int)
        assert environment.type == "environment"
        assert environment.creation_time
        assert environment.state().contents == "foo"

    def test_create_environment_get_observed(self):
        environment = nodes.Environment()
        state = information.State(origin=environment, contents="foo")
        self.add(environment, state)

        agent = nodes.ReplicatorAgent()
        self.add(agent)

        environment.connect(direction="to", whom=agent)
        environment.transmit(to_whom=agent)
        agent.receive()

        assert agent.infos()[0].contents == "foo"
