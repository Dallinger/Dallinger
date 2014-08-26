from wallace import models, agents, memes, db


class TestAgents(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_agent(self):
        agent = agents.Agent()
        self.add(agent)

        assert agent.genome_id is None
        assert agent.mimeme_id is None

        genome = memes.Genome(contents="foo")
        mimeme = memes.Mimeme(contents="bar")
        self.add(genome, mimeme)

        agent.genome = genome
        agent.mimeme = mimeme
        self.db.commit()

        assert agent.genome_id == genome.id
        assert agent.genome.contents == "foo"

        assert agent.mimeme_id == mimeme.id
        assert agent.mimeme.contents == "bar"

    def test_agent_transmit(self):
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        agent1.connect_to(agent2)
        genome = memes.Genome(contents="foo")
        mimeme = memes.Mimeme(contents="bar")
        self.add(agent1, agent2, genome, mimeme)

        agent1.genome = genome
        agent1.mimeme = mimeme
        self.db.commit()

        agent1.transmit(agent2)
        self.db.commit()

        assert agent1.genome.contents == agent2.genome.contents
        assert agent1.genome.id != agent2.genome.id
        assert agent1.mimeme.contents == agent2.mimeme.contents
        assert agent1.mimeme.id != agent2.mimeme.id

    def test_agent_broadcast(self):
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        agent3 = agents.Agent()
        agent1.connect_to(agent2)
        agent1.connect_to(agent3)
        genome = memes.Genome(contents="foo")
        mimeme = memes.Mimeme(contents="bar")
        self.add(agent1, agent2, agent3, genome, mimeme)

        agent1.genome = genome
        agent1.mimeme = mimeme
        self.db.commit()

        agent1.broadcast()
        self.db.commit()

        assert agent1.genome.contents == agent2.genome.contents
        assert agent1.genome.contents == agent3.genome.contents
        assert agent1.genome.id != agent2.genome.id != agent3.genome.id
        assert agent1.mimeme.contents == agent2.mimeme.contents
        assert agent1.mimeme.contents == agent3.mimeme.contents
        assert agent1.mimeme.id != agent2.mimeme.id != agent3.genome.id

    def test_create_random_binary_string_source(self):
        source = agents.RandomBinaryStringSource()
        self.add(source)

        assert source.genome_size == 8
        assert source.mimeme_size == 8

    def test_create_random_binary_string_source_genome_size_4(self):
        source = agents.RandomBinaryStringSource(genome_size=4)
        self.add(source)

        assert source.genome_size == 4
        assert source.mimeme_size == 8

    def test_create_random_binary_string_source_mimeme_size_4(self):
        source = agents.RandomBinaryStringSource(mimeme_size=4)
        self.add(source)

        assert source.genome_size == 8
        assert source.mimeme_size == 4

    def test_generate_random_binary_string_genome(self):
        source = agents.RandomBinaryStringSource(genome_size=2)
        self.add(source)

        genome = source.generate_genome()
        assert genome.contents in ["00", "01", "10", "11"]

    def test_generate_random_binary_string_mimeme(self):
        source = agents.RandomBinaryStringSource(mimeme_size=2)
        self.add(source)

        mimeme = source.generate_mimeme()
        assert mimeme.contents in ["00", "01", "10", "11"]

    def test_transmit_random_binary_string_source(self):
        source = agents.RandomBinaryStringSource(genome_size=2, mimeme_size=2)
        agent = agents.Agent()
        source.connect_to(agent)
        self.add(source, agent)

        source.transmit(agent)
        self.db.commit()

        assert agent.genome.contents in ["00", "01", "10", "11"]
        assert agent.mimeme.contents in ["00", "01", "10", "11"]

    def test_broadcast_random_binary_string_source(self):
        source = agents.RandomBinaryStringSource(
            genome_size=100, mimeme_size=100)
        agent1 = agents.Agent()
        agent2 = agents.Agent()
        source.connect_to(agent1)
        source.connect_to(agent2)
        self.add(source, agent1, agent2)

        source.broadcast()
        self.db.commit()

        assert agent1.genome.contents != agent2.genome.contents
        assert agent1.mimeme.contents != agent2.mimeme.contents
