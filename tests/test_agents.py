"""Tests for creating and manipulating agents."""

from pytest import raises

from dallinger import information, models, nodes
from dallinger.information import Gene, Meme


class TestAgents(object):
    """The agent test class."""

    def test_create_agent_generic(self, a):
        agent = a.agent()
        assert isinstance(agent, nodes.Agent)

    def test_create_agent_with_participant(self, a):
        participant = a.participant()
        agent = a.agent(participant=participant)
        assert agent.participant_id == participant.id

    def test_fitness_property(self, a):
        agent = a.agent()
        agent.fitness = 1.99999
        assert agent.fitness == 1.99999

    def test_fitness_expression_search_match(self, a):
        agent = a.agent()
        agent.fitness = 1.99999
        results = nodes.Agent.query.filter_by(fitness=1.99999).all()
        assert len(results) == 1
        assert results[0] is agent

    def test_fitness_expression_search_requires_exact_match(self, a):
        agent = a.agent()
        agent.fitness = 1.99999
        results = nodes.Agent.query.filter_by(fitness=1.9999).all()
        assert len(results) == 0

    def test_create_agent_generic_transmit_to_all(self, a):
        net = a.network()
        agent1 = a.agent(network=net)
        agent2 = a.agent(network=net)
        agent3 = a.agent(network=net)

        agent1.connect(direction="to", whom=agent2)
        agent1.connect(direction="to", whom=agent3)
        assert agent1.transmit(to_whom=models.Node) == []

    def test_fail_agent_assigns_time_of_death(self, a):
        agent = a.agent()
        assert agent.failed is False and agent.time_of_death is None

        agent.fail()
        assert agent.failed is True and agent.time_of_death is not None

    def test_create_replicator_agent(self, a):
        agent = a.replicator()
        info = a.info(origin=agent, contents="foo")
        assert agent.infos()[0] == info

    def test_can_only_connect_failed_infos_to_failed_node(self, a):
        net = a.network()
        agent = a.agent(network=net)
        agent.fail()

        with raises(ValueError):
            info = a.info(origin=agent, contents="foo")
        info = a.info(origin=agent, contents="foo", failed=True)
        assert agent.infos() == []
        assert agent.infos(failed=True) == [info]

    def test_agent_transmit(self, a):
        net = a.network()
        agent1 = a.replicator(network=net)
        agent2 = a.replicator(network=net)
        agent1.connect(direction="to", whom=agent2)
        info = a.info(origin=agent1, contents="foo")
        agent1.transmit(what=agent1.infos()[0], to_whom=agent2)
        agent2.receive()

        assert agent1.infos()[0].contents == agent2.infos()[0].contents
        assert agent1.infos()[0].id != agent2.infos()[0].id

        transmission = info.transmissions()[0]
        assert transmission.info_id == info.id
        assert transmission.origin_id == agent1.id
        assert transmission.destination_id == agent2.id

    def test_agent_transmit_no_connection(self, a):
        net = a.network()
        agent1 = a.replicator(network=net)
        agent2 = a.replicator(network=net)
        info = models.Info(origin=agent1)
        with raises(ValueError):
            agent1.transmit(what=info, to_whom=agent2)

    def test_agent_transmit_invalid_info(self, a):
        net = a.network()
        agent1 = a.replicator(network=net)
        agent2 = a.replicator(network=net)
        agent1.connect(direction="to", whom=agent2)
        info = a.info(origin=agent2)

        with raises(ValueError) as ex_info:
            agent1.transmit(what=info, to_whom=agent2)
            assert ex_info.match("they do not have the same origin")

    def test_agent_transmit_everything_to_everyone(self, a):
        net = a.network()
        agent1 = a.replicator(network=net)
        agent2 = a.replicator(network=net)
        agent3 = a.replicator(network=net)
        agent1.connect(direction="to", whom=agent2)
        agent1.connect(direction="to", whom=agent3)
        info = a.info(origin=agent1)
        agent1.transmit(what=models.Info, to_whom=nodes.Agent)
        agent2.receive()
        agent3.receive()

        assert agent1.infos()[0].contents == agent2.infos()[0].contents
        assert agent1.infos()[0].contents == agent3.infos()[0].contents
        assert agent1.infos()[0].id != agent2.infos()[0].id != agent3.infos()[0].id

        transmissions = info.transmissions()
        assert len(transmissions) == 2

    def test_transmit_selector_default(self, a):
        net = a.network()
        agent1 = a.replicator(network=net)
        agent2 = a.replicator(network=net)
        agent1.connect(direction="to", whom=agent2)

        a.meme(origin=agent1, contents="foo")
        a.gene(origin=agent1, contents="bar")

        assert len(agent1.infos(type=Gene)) == 1
        assert len(agent1.infos(type=Meme)) == 1
        assert len(agent2.infos(type=Gene)) == 0
        assert len(agent2.infos(type=Meme)) == 0

        # Transmit from agent 1 to 2.
        agent1.transmit(to_whom=agent2)

        # Receive the transmission.
        agent2.receive()

        # Make sure that Agent 2 has a blank memome and the right gene.
        assert "foo" == agent2.infos(type=Meme)[0].contents
        assert "bar" == agent2.infos(type=Gene)[0].contents

    def test_transmit_selector_specific_info(self, a):
        net = a.network()
        agent1 = a.replicator(network=net)
        agent2 = a.replicator(network=net)
        agent1.connect(direction="to", whom=agent2)
        a.meme(origin=agent1)
        gene = a.gene(origin=agent1, contents="foo")

        assert len(agent1.infos(type=Gene)) == 1
        assert len(agent1.infos(type=Meme)) == 1
        assert len(agent2.infos(type=Gene)) == 0
        assert len(agent2.infos(type=Meme)) == 0

        # Transmit from agent 1 to 2.
        agent1.transmit(what=gene, to_whom=agent2)

        # Receive the transmission.
        agent2.receive()

        # Make sure that Agent 2 has a blank memome and the right gene.
        assert not agent2.infos(type=Meme)
        assert "foo" == agent2.infos(type=Gene)[0].contents

    def test_transmit_selector_all_of_type(self, a):
        net = a.network()
        agent1 = a.replicator(network=net)
        agent2 = a.replicator(network=net)
        agent1.connect(direction="to", whom=agent2)

        a.meme(origin=agent1)
        a.meme(origin=agent1)
        a.meme(origin=agent1)
        a.gene(origin=agent1)

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
