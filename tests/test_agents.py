"""Tests for creating and manipulating agents."""

from wallace import nodes, information, db, models
from wallace.information import Meme, Gene
from nose.tools import raises


class TestAgents(object):

    """The agent test class."""

    def setup(self):
        """Set up the environment by resetting the tables."""
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_create_agent_generic(self):
        net = models.Network()
        self.db.add(net)
        agent = nodes.Agent(network=net)
        assert agent

    def test_create_agent_generic_transmit_to_all(self):
        net = models.Network()
        self.db.add(net)
        agent1 = nodes.Agent(network=net)
        agent2 = nodes.Agent(network=net)
        agent3 = nodes.Agent(network=net)

        agent1.connect(direction="to", whom=agent2)
        agent1.connect(direction="to", whom=agent3)
        agent1.transmit(to_whom=models.Node)

    def test_fail_agent(self):
        net = models.Network()
        self.db.add(net)
        agent = nodes.Agent(network=net)
        self.db.commit()

        assert agent.failed is False
        assert agent.time_of_death is None

        agent.fail()
        assert agent.failed is True
        assert agent.time_of_death is not None

    def test_create_replicator_agent(self):
        net = models.Network()
        self.db.add(net)
        agent = nodes.ReplicatorAgent(network=net)

        assert len(agent.infos()) is 0

        info = information.Info(origin=agent, contents="foo")

        assert agent.infos()[0] == info

    def test_agent_transmit(self):
        net = models.Network()
        self.db.add(net)

        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)

        agent1.connect(direction="to", whom=agent2)

        info = models.Info(origin=agent1, contents="foo")

        agent1.transmit(what=agent1.infos()[0], to_whom=agent2)
        agent2.receive()

        assert agent1.infos()[0].contents == agent2.infos()[0].contents
        assert agent1.infos()[0].id != agent2.infos()[0].id

        transmission = info.transmissions()[0]
        assert transmission.info_id == info.id
        assert transmission.origin_id == agent1.id
        assert transmission.destination_id == agent2.id

    @raises(ValueError)
    def test_agent_transmit_no_connection(self):
        net = models.Network()
        self.db.add(net)
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        info = models.Info(origin=agent1, contents="foo")
        agent1.transmit(what=info, to_whom=agent2)

    @raises(ValueError)
    def test_agent_transmit_invalid_info(self):
        net = models.Network()
        self.db.add(net)
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)

        agent1.connect(direction="to", whom=agent2)
        info = models.Info(origin=agent2, contents="foo")

        agent1.transmit(what=info, to_whom=agent2)

    def test_agent_transmit_everything_to_everyone(self):
        net = models.Network()
        self.db.add(net)
        self.db.commit()

        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)

        agent1.connect(direction="to", whom=agent2)
        agent1.connect(direction="to", whom=agent3)
        info = models.Info(origin=agent1, contents="foo")

        agent1.transmit(what=models.Info, to_whom=nodes.Agent)

        agent2.receive()
        agent3.receive()

        assert agent1.infos()[0].contents == agent2.infos()[0].contents
        assert agent1.infos()[0].contents == agent3.infos()[0].contents
        assert agent1.infos()[0].id != agent2.infos()[0].id != agent3.infos()[0].id

        transmissions = info.transmissions()
        assert len(transmissions) == 2

    def test_transmit_selector_default(self):
        net = models.Network()
        self.db.add(net)
        # Create a network of two biological nodes.
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)

        agent1.connect(direction="to", whom=agent2)

        information.Meme(origin=agent1, contents="foo")
        information.Gene(origin=agent1, contents="bar")

        assert len(agent1.infos(type=Gene)) == 1
        assert len(agent1.infos(type=Gene)) == 1
        assert len(agent2.infos(type=Gene)) == 0
        assert len(agent2.infos(type=Gene)) == 0

        # Transmit from agent 1 to 2.
        agent1.transmit(to_whom=agent2)

        # Receive the transmission.
        agent2.receive()

        # Make sure that Agent 2 has a blank memome and the right gene.
        assert "foo" == agent2.infos(type=Meme)[0].contents
        assert "bar" == agent2.infos(type=Gene)[0].contents

    def test_transmit_selector_specific_info(self):
        net = models.Network()
        self.db.add(net)
        # Create a network of two biological nodes.
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)

        agent1.connect(direction="to", whom=agent2)

        information.Meme(origin=agent1, contents="foo")
        gene = information.Gene(origin=agent1, contents="bar")

        assert len(agent1.infos(type=Gene)) == 1
        assert len(agent1.infos(type=Gene)) == 1
        assert len(agent2.infos(type=Gene)) == 0
        assert len(agent2.infos(type=Gene)) == 0

        # Transmit from agent 1 to 2.
        agent1.transmit(what=gene, to_whom=agent2)

        # Receive the transmission.
        agent2.receive()

        # Make sure that Agent 2 has a blank memome and the right gene.
        assert not agent2.infos(type=Meme)
        assert "bar" == agent2.infos(type=Gene)[0].contents

    def test_transmit_selector_all_of_type(self):
        net = models.Network()
        self.db.add(net)

        # Create a network of two biological nodes.
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)

        agent1.connect(direction="to", whom=agent2)

        information.Meme(origin=agent1, contents="foo1")
        information.Meme(origin=agent1, contents="foo2")
        information.Meme(origin=agent1, contents="foo3")
        information.Gene(origin=agent1, contents="bar")

        assert len(agent1.infos(type=Meme)) == 3
        assert len(agent2.infos(type=Meme)) == 0
        assert len(agent1.infos(type=Gene)) == 1
        assert len(agent2.infos(type=Gene)) == 0

        # Transmit memes from agent 1 to 2.
        agent1.transmit(what=information.Meme, to_whom=agent2)

        # Receive the transmission.
        agent2.receive()

        # Make sure that Agent 2 has a blank memome and the right gene.
        assert not agent2.infos(type=Gene)
        assert len(agent2.infos(type=Meme)) == 3
