from wallace import agents, information, db


class TestBiologicalAgents(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_agents(self):
        agent = agents.Agent()
        self.add(agent)

        assert agent.ome is None
        assert len(agent.omes) == 1

        ome = information.Info(origin=agent, contents="foo")
        self.add(ome)
        self.db.commit()

        assert agent.ome == ome

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

    def test_create_biological_agent(self):
        agent = agents.BiologicalAgent()
        self.add(agent)

        assert agent.genome is None
        assert agent.memome is None

        assert len(agent.omes) == 2

        genome = information.Genome(origin=agent, contents="foo")
        memome = information.Memome(origin=agent, contents="bar")
        self.add(genome, memome)
        self.db.commit()

        assert agent.genome == genome
        assert agent.memome == memome

    def test_agent_transmit(self):
        agent1 = agents.BiologicalAgent()
        agent2 = agents.BiologicalAgent()
        agent1.connect_to(agent2)
        genome = information.Genome(origin=agent1, contents="foo")
        memome = information.Memome(origin=agent1, contents="bar")
        self.add(agent1, agent2, genome, memome)
        self.db.commit()

        agent1.transmit(agent2)
        self.db.commit()

        agent2.receive_all()
        self.db.commit()

        assert agent1.genome.contents == agent2.genome.contents
        assert agent1.genome.uuid != agent2.genome.uuid
        assert agent1.memome.contents == agent2.memome.contents
        assert agent1.memome.uuid != agent2.memome.uuid

    def test_agent_broadcast(self):
        agent1 = agents.BiologicalAgent()
        agent2 = agents.BiologicalAgent()
        agent3 = agents.BiologicalAgent()
        agent1.connect_to(agent2)
        agent1.connect_to(agent3)
        genome = information.Genome(origin=agent1, contents="foo")
        memome = information.Memome(origin=agent1, contents="bar")
        self.add(agent1, agent2, agent3, genome, memome)
        self.db.commit()

        agent1.broadcast()
        self.db.commit()

        agent2.receive_all()
        agent3.receive_all()
        self.db.commit()

        assert agent1.genome.contents == agent2.genome.contents
        assert agent1.genome.contents == agent3.genome.contents
        assert agent1.genome.uuid != agent2.genome.uuid != agent3.genome.uuid
        assert agent1.memome.contents == agent2.memome.contents
        assert agent1.memome.contents == agent3.memome.contents
        assert agent1.memome.uuid != agent2.memome.uuid != agent3.genome.uuid
