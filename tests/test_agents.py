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

    def test_create_agent(self):
        agent = agents.BiologicalAgent()
        self.add(agent)

        assert agent.genome is None
        assert agent.memome is None

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

        assert source.genome_size == 8
        assert source.memome_size == 8

    def test_create_random_binary_string_source_genome_size_4(self):
        source = agents.RandomBinaryStringSource(genome_size=4)
        self.add(source)

        assert source.genome_size == 4
        assert source.memome_size == 8

    def test_create_random_binary_string_source_memome_size_4(self):
        source = agents.RandomBinaryStringSource(memome_size=4)
        self.add(source)

        assert source.genome_size == 8
        assert source.memome_size == 4

    def test_generate_random_binary_string_genome(self):
        source = agents.RandomBinaryStringSource(genome_size=2)
        self.add(source)

        genome = source.generate_genome()
        assert genome.contents in ["00", "01", "10", "11"]

    def test_generate_random_binary_string_memome(self):
        source = agents.RandomBinaryStringSource(memome_size=2)
        self.add(source)

        memome = source.generate_memome()
        assert memome.contents in ["00", "01", "10", "11"]

    def test_transmit_random_binary_string_source(self):
        source = agents.RandomBinaryStringSource(genome_size=2, memome_size=2)
        agent = agents.BiologicalAgent()
        source.connect_to(agent)
        self.add(source, agent)

        source.transmit(agent)
        self.db.commit()

        agent.receive_all()
        self.db.commit()

        assert agent.genome.contents in ["00", "01", "10", "11"]
        assert agent.memome.contents in ["00", "01", "10", "11"]

    def test_broadcast_random_binary_string_source(self):
        source = agents.RandomBinaryStringSource(
            genome_size=100, memome_size=100)
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

        assert agent1.genome.contents != agent2.genome.contents
        assert agent1.memome.contents != agent2.memome.contents
