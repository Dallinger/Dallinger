from wallace import processes, networks, sources, agents, db


class TestProcesses(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def test_random_walk_from_source(self):

        net = networks.Network()

        agent1 = agents.ReplicatorAgent()
        agent2 = agents.ReplicatorAgent()
        agent3 = agents.ReplicatorAgent()

        net.add(agent1)
        net.add(agent2)
        net.add(agent3)

        agent1.connect_to(agent2)
        agent2.connect_to(agent3)

        self.db.add_all([agent1, agent2, agent3])

        source = sources.RandomBinaryStringSource()
        self.db.add(source)

        net.add(source)
        source.connect_to(net.agents[0])
        source.create_information()
        self.db.commit()

        process = processes.RandomWalkFromSource(net)
        process.step()

        agent1.receive_all()
        msg = agent1.info.contents

        process.step()
        agent2.receive_all()

        process.step()
        agent3.receive_all()

        assert msg == agent3.info.contents

    def test_moran_process_cultural(self):

        # Create a fully-connected network.
        net = networks.Network()

        agent1 = agents.ReplicatorAgent()
        agent2 = agents.ReplicatorAgent()
        agent3 = agents.ReplicatorAgent()
        self.db.add_all([agent1, agent2, agent3])

        net.add(agent1)
        net.add(agent2)
        net.add(agent3)

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
        source.connect_to(net.agents)
        info = source.create_information()
        self.db.commit()
        source.transmit(what=info)

        for agent in net.agents:
            agent.receive_all()

        # Run a Moran process for 100 steps.
        process = processes.MoranProcessCultural(net)

        for i in range(100):
            process.step()
            for agent in net.agents:
                agent.receive_all()

        # Ensure that the process had reached fixation.
        assert agent1.info.contents == agent2.info.contents
        assert agent2.info.contents == agent3.info.contents
        assert agent3.info.contents == agent1.info.contents

    # def test_moran_process_sexual(self):  # FIXME

    #     # Create a fully-connected network.
    #     net = networks.Network()
    #     self.db.add(net)

    #     agent1 = agents.ReplicatorAgent()
    #     agent2 = agents.ReplicatorAgent()
    #     agent3 = agents.ReplicatorAgent()
    #     self.db.add_all([agent1, agent2, agent3])

    #     net.add(agent1)
    #     net.add(agent2)
    #     net.add(agent3)

    #     vector1 = agent1.connect_to(agent2)
    #     vector2 = agent1.connect_to(agent3)
    #     vector3 = agent2.connect_to(agent1)
    #     vector4 = agent2.connect_to(agent3)
    #     vector5 = agent3.connect_to(agent1)
    #     vector6 = agent3.connect_to(agent2)

    #     self.db.add_all(
    #    [vector1, vector2, vector3, vector4, vector5, vector6])

    #     # Add a global source and broadcast to all the agents.
    #     source = sources.RandomBinaryStringSource()
    #     self.db.add(source)

    #     net.add(source)
    #     source.connect_to(net.agents)

    #     info = source.create_information()
    #     self.db.add(info)

    #     source.transmit(what=info)

    #     for agent in net.agents:
    #         agent.receive_all()

    #     all_contents = [agent1.info.contents,
    #                     agent2.info.contents,
    #                     agent3.info.contents]

    #     # Run a Moran process for 100 steps.
    #     process = processes.MoranProcessSexual(net)

    #     for i in range(100):
    #         process.step()
    #         for agent in net.agents:
    #             agent.receive_all()

    #     # Ensure that the process had reached fixation.
    #     assert agent1.status == "dead"
    #     assert agent2.status == "dead"
    #     assert agent3.status == "dead"

    #     for agent in net.agents:
    #         assert agent.info.contents in all_contents
