import pytest

from dallinger import models, networks, nodes, processes
from dallinger.nodes import Agent


class TestProcesses(object):
    def test_random_walk_from_source(self, db_session):
        net = models.Network()
        db_session.add(net)
        db_session.commit()

        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)

        agent1.connect(whom=agent2)
        agent2.connect(whom=agent3)

        source = nodes.RandomBinaryStringSource(network=net)

        from operator import attrgetter

        source.connect(whom=min(net.nodes(type=Agent), key=attrgetter("creation_time")))
        source.create_information()

        processes.random_walk(net)

        agent1.receive()
        msg = agent1.infos()[0].contents

        processes.random_walk(net)
        agent2.receive()
        agent2.infos()[0].contents

        processes.random_walk(net)
        agent3.receive()
        agent3.infos()[0].contents

        assert msg == agent3.infos()[0].contents

    @pytest.mark.slow
    def test_moran_process_cultural(self, db_session):
        # Create a fully-connected network.
        net = models.Network()
        db_session.add(net)
        db_session.commit()

        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)
        db_session.commit()

        agent1.connect(whom=agent2)
        agent1.connect(whom=agent3)
        agent2.connect(whom=agent1)
        agent2.connect(whom=agent3)
        agent3.connect(whom=agent1)
        agent3.connect(whom=agent2)

        # Add a global source and broadcast to all the nodes.
        source = nodes.RandomBinaryStringSource(network=net)
        for agent in net.nodes(type=Agent):
            source.connect(whom=agent)
            source.transmit(to_whom=agent)
            agent.receive()

        # Run a Moran process for 100 steps.
        for i in range(100):
            processes.moran_cultural(net)
            for agent in net.nodes(type=Agent):
                agent.receive()

        # Ensure that the process had reached fixation.
        from operator import attrgetter

        assert (
            max(agent1.infos(), key=attrgetter("creation_time")).contents
            == max(agent2.infos(), key=attrgetter("creation_time")).contents
        )
        assert (
            max(agent2.infos(), key=attrgetter("creation_time")).contents
            == max(agent3.infos(), key=attrgetter("creation_time")).contents
        )
        assert (
            max(agent3.infos(), key=attrgetter("creation_time")).contents
            == max(agent1.infos(), key=attrgetter("creation_time")).contents
        )

    @pytest.mark.slow
    def test_moran_process_sexual(self, db_session):
        # Create a fully-connected network.
        net = networks.Network()
        db_session.add(net)
        db_session.commit()

        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)

        agent1.connect(direction="both", whom=[agent2, agent3])
        agent2.connect(direction="both", whom=agent3)

        # Add a global source and broadcast to all the nodes.
        source = nodes.RandomBinaryStringSource(network=net)
        source.connect(direction="to", whom=net.nodes(type=Agent))

        source.create_information()

        for agent in net.nodes(type=Agent):
            source.transmit(to_whom=agent)
            agent.receive()

        # Run a Moran process for 100 steps.
        for i in range(100):
            nodes.ReplicatorAgent(network=net)
            processes.moran_sexual(net)
            for agent in net.nodes(type=Agent):
                agent.receive()

        # Ensure that the process had reached fixation.
        assert agent1.failed is True
        assert agent2.failed is True
        assert agent3.failed is True

        for a in net.nodes(type=Agent):
            for a2 in net.nodes(type=Agent):
                assert a.infos()[0].contents == a2.infos()[0].contents
