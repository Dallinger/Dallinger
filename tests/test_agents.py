from wallace import models, agents, information, db


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

    def test_create_random_binary_string_source(self):
        source = agents.RandomBinaryStringSource()
        self.add(source)

        assert source.ome_size == 8

    def test_create_random_binary_string_source_ome_size_4(self):
        source = agents.RandomBinaryStringSource(ome_size=4)
        self.add(source)

        assert source.ome_size == 4

    def test_generate_random_binary_string_genome(self):
        source = agents.RandomBinaryStringSource(ome_size=2)
        self.add(source)

        ome = source.ome
        assert ome.contents in ["00", "01", "10", "11"]

    def test_generate_random_binary_string_memome(self):
        source = agents.RandomBinaryStringSource(ome_size=2)
        self.add(source)

        ome = source.ome
        assert ome.contents in ["00", "01", "10", "11"]

    def test_transmit_random_binary_string_source(self):
        source = agents.RandomBinaryStringSource(ome_size=2)
        agent = agents.BiologicalAgent()
        source.connect_to(agent)
        self.add(source, agent)

        source.transmit(agent)
        self.db.commit()

        agent.receive_all()
        self.db.commit()

        assert agent.ome.contents in ["00", "01", "10", "11"]

    def test_broadcast_random_binary_string_source(self):
        source = agents.RandomBinaryStringSource(ome_size=100)
        agent1 = agents.BiologicalAgent()
        agent2 = agents.BiologicalAgent()
        source.connect_to(agent1)
        source.connect_to(agent2)
        self.add(source, agent1, agent2)

        source.broadcast()
        self.db.commit()

        agent1.receive_all()
        agent2.receive_all()
        self.db.commit()

        assert agent1.ome.contents != agent2.ome.contents
