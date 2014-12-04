from wallace import agents, information, db
from nose.tools import raises


class TestAgents(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_agent_generic(self):
        agent = agents.Agent()
        self.add(agent)

        assert agent

    @raises(NotImplementedError)
    def test_create_agent_generic_transmit(self):
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        self.add(agent1, agent2)
        agent1.transmit(agent2)

    @raises(NotImplementedError)
    def test_create_agent_generic_broadcast(self):
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        agent3 = agents.Agent()
        agent1.connect_to(agent2)
        agent1.connect_to(agent3)
        self.add(agent1, agent2, agent3)
        agent1.broadcast()

    def test_kill_agent(self):
        agent = agents.Agent()
        self.add(agent)

        assert agent.status == "alive"

        agent.kill()
        assert agent.status == "dead"

    def test_fail_agent(self):
        agent = agents.Agent()
        self.add(agent)

        assert agent.status == "alive"
        assert agent.time_of_death is None

        agent.fail()
        assert agent.status == "failed"
        assert agent.time_of_death is not None

    def test_create_replicator_agent(self):
        agent = agents.ReplicatorAgent()
        self.add(agent)

        assert agent.info is None

        info = information.Info(origin=agent, contents="foo")
        self.add(info)
        self.db.commit()

        assert agent.info == info

    def test_agent_transmit(self):
        agent1 = agents.ReplicatorAgent()
        agent2 = agents.ReplicatorAgent()
        agent1.connect_to(agent2)
        info = information.Info(origin=agent1, contents="foo")
        self.add(agent1, agent2, info)
        self.db.commit()

        agent1.transmit(agent2)
        self.db.commit()

        agent2.receive_all()
        self.db.commit()

        assert agent1.info.contents == agent2.info.contents
        assert agent1.info.uuid != agent2.info.uuid

    def test_agent_broadcast(self):
        agent1 = agents.ReplicatorAgent()
        agent2 = agents.ReplicatorAgent()
        agent3 = agents.ReplicatorAgent()
        agent1.connect_to(agent2)
        agent1.connect_to(agent3)
        info = information.Gene(origin=agent1, contents="foo")
        self.add(agent1, agent2, agent3, info)
        self.db.commit()

        agent1.broadcast()
        self.db.commit()

        agent2.receive_all()
        agent3.receive_all()
        self.db.commit()

        assert agent1.info.contents == agent2.info.contents
        assert agent1.info.contents == agent3.info.contents
        assert agent1.info.uuid != agent2.info.uuid != agent3.info.uuid
