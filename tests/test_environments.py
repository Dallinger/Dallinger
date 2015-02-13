from wallace import sources, agents, db, environments, information


class TestEnvironments(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_environment(self):
        """Create an environment"""
        environment = environments.Environment()
        state = information.State(origin=environment, contents="foo")
        self.add(environment, state)

        assert len(environment.uuid) == 32
        assert environment.type == "environment"
        assert environment.creation_time
        assert environment.state.contents == "foo"

    def test_create_environment_get_observed(self):
        environment = environments.Environment()
        state = information.State(origin=environment, contents="foo")
        self.add(environment, state)

        agent = agents.ReplicatorAgent()
        self.add(agent)

        agent.observe(environment)
        # raw_input()

        assert agent.info.contents == "foo"
