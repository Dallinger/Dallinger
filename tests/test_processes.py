from wallace import processes, networks, sources, agents, db, models
from wallace.models import Agent, Network


class TestProcesses(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def test_random_walk_from_source(self):

        net = models.Network()

        agent1 = agents.ReplicatorAgent()
        agent2 = agents.ReplicatorAgent()
        agent3 = agents.ReplicatorAgent()

        net.add(agent1)
        net.add(agent2)
        net.add(agent3)
        self.db.add(agent1)
        self.db.add(agent2)
        self.db.add(agent3)
        self.db.commit()

        agent1.connect_to(agent2)
        agent2.connect_to(agent3)

        source = sources.RandomBinaryStringSource()
        self.db.add(source)

        net.add(source)
        source.connect_to(net.nodes(type=Agent)[0])
        source.create_information()

        processes.random_walk(net)

        agent1.receive_all()
        msg = agent1.infos()[0].contents

        processes.random_walk(net)
        agent2.receive_all()

        processes.random_walk(net)
        agent3.receive_all()

        assert msg == agent3.infos()[0].contents

    def test_moran_process_cultural(self):

        # Create a fully-connected network.
        net = models.Network()

        agent1 = agents.ReplicatorAgent()
        agent2 = agents.ReplicatorAgent()
        agent3 = agents.ReplicatorAgent()
        self.db.add_all([agent1, agent2, agent3])
        net.add([agent1, agent2, agent3])
        self.db.commit()

        agent1.connect_to(agent2)
        agent1.connect_to(agent3)
        agent2.connect_to(agent1)
        agent2.connect_to(agent3)
        agent3.connect_to(agent1)
        agent3.connect_to(agent2)

        # Add a global source and broadcast to all the agents.
        source = sources.RandomBinaryStringSource()
        self.db.add(source)
        net.add(source)
        for agent in net.nodes(type=Agent):
            source.connect_to(agent)
            source.transmit(to_whom=agent)
            agent.receive_all()

        # Run a Moran process for 100 steps.
        for i in xrange(100):
            processes.moran_cultural(net)
            for agent in net.nodes(type=Agent):
                agent.receive_all()

        # Ensure that the process had reached fixation.
        assert agent1.infos()[-1].contents == agent2.infos()[-1].contents
        assert agent2.infos()[-1].contents == agent3.infos()[-1].contents
        assert agent3.infos()[-1].contents == agent1.infos()[-1].contents

    def test_moran_process_sexual(self):

        # Create a fully-connected network.
        net = networks.Network()
        self.db.add(net)

        agent1 = agents.ReplicatorAgent()
        agent2 = agents.ReplicatorAgent()
        agent3 = agents.ReplicatorAgent()
        self.db.add_all([agent1, agent2, agent3])
        self.db.commit()

        net.add([agent1, agent2, agent3])

        agent1.connect_to(agent2)
        agent1.connect_to(agent3)
        agent2.connect_to(agent1)
        agent2.connect_to(agent3)
        agent3.connect_to(agent1)
        agent3.connect_to(agent2)

        # Add a global source and broadcast to all the agents.
        source = sources.RandomBinaryStringSource()
        self.db.add(source)

        net.add(source)
        source.connect_to(net.nodes(type=Agent))

        info = source.create_information()
        self.db.add(info)

        for agent in net.nodes(type=Agent):
            source.transmit(to_whom=agent)
            agent.receive_all()

        # Run a Moran process for 100 steps.
        for i in range(100):
            newcomer = agents.ReplicatorAgent()
            net.add(newcomer)
            self.db.add(newcomer)
            processes.moran_sexual(net)
            for agent in net.nodes(type=Agent):
                agent.receive_all()

        # Ensure that the process had reached fixation.
        assert agent1.status == "dead"
        assert agent2.status == "dead"
        assert agent3.status == "dead"

        for a in net.nodes(type=Agent):
            for a2 in net.nodes(type=Agent):
                assert a.infos()[0].contents == a2.infos()[0].contents
