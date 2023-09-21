"""Test the classes in models.py."""

from __future__ import print_function

import sys
from datetime import datetime

import six
from pytest import mark, raises

from dallinger import models, nodes
from dallinger.db import Base, get_all_mapped_classes, get_polymorphic_mapping
from dallinger.information import Gene
from dallinger.nodes import Agent, Source
from dallinger.transformations import Mutation


@mark.slow
class TestModels(object):
    def add(self, session, *args):
        session.add_all(args)
        session.commit()

    def test_models(self, db_session):
        """####################
        #### Test Network ####
        ####################"""

        print("")
        print("Testing models: Network", end="\r")
        sys.stdout.flush()

        # create test network:
        net = models.Network()
        db_session.add(net)
        db_session.commit()
        net = models.Network.query.one()

        # create a participant
        participant = models.Participant(
            recruiter_id="hotair",
            worker_id=str(1),
            hit_id=str(1),
            assignment_id=str(1),
            mode="test",
        )
        db_session.add(participant)
        db_session.commit()

        # create some nodes
        node = models.Node(network=net)
        agent = Agent(network=net, participant=participant)
        source = Source(network=net)

        # create vectors
        source.connect(direction="to", whom=agent)
        agent.connect(direction="both", whom=node)

        # create some infos
        info = models.Info(origin=agent, contents="ethwth")
        gene = Gene(origin=source, contents="hkhkhkh")

        # conditionally transmit and transform
        source.transmit(what=models.Info)
        agent.receive()
        agent.transmit(what=Gene)
        models.Transformation(info_in=gene, info_out=info)

        # Test attributes

        assert net.id == 1
        assert isinstance(net.creation_time, datetime)
        assert net.property1 is None
        assert net.property2 is None
        assert net.property3 is None
        assert net.property4 is None
        assert net.property5 is None
        assert net.details == {}
        assert net.failed is False
        assert net.time_of_death is None
        assert net.type == "network"
        assert isinstance(net.max_size, int)
        assert net.max_size == 1e6
        assert isinstance(net.full, bool)
        assert net.full is False
        assert isinstance(net.role, six.text_type)
        assert net.role == "default"

        # test __repr__()
        assert repr(net) == (
            "<Network-1-network with 3 nodes, 3 vectors, 2 infos, "
            "1 transmissions and 1 transformations>"
        )

        # test __json__()
        assert net.__json__() == {
            "id": 1,
            "type": "network",
            "max_size": 1e6,
            "full": False,
            "role": "default",
            "creation_time": net.creation_time,
            "failed": False,
            "failed_reason": None,
            "time_of_death": None,
            "property1": None,
            "property2": None,
            "property3": None,
            "property4": None,
            "property5": None,
            "details": {},
            "n_alive_nodes": 3,
            "n_failed_nodes": 0,
            "n_completed_infos": 2,
            "n_pending_infos": 0,
            "n_failed_infos": 0,
            "object_type": "Network",
        }

        # test nodes()
        for n in [node, agent, source]:
            assert n in net.nodes()

        assert net.nodes(type=Agent) == [agent]

        assert net.nodes(failed=True) == []
        for n in [node, agent, source]:
            assert n in net.nodes(failed="all")

        assert net.nodes(participant_id=1) == [agent]

        # test size()
        assert net.size() == 3
        assert net.size(type=Source) == 1
        assert net.size(type=Agent) == 1
        assert net.size(failed=True) == 0
        assert net.size(failed="all") == 3

        # test infos()
        assert len(net.infos(failed="all")) == 2
        assert len(net.infos(type=models.Info, failed="all")) == 2
        assert len(net.infos(type=Gene, failed="all")) == 1
        assert len(net.infos(type=Gene)) == 1
        assert len(net.infos(failed=True)) == 0

        # test Network.transmissions()
        assert len(net.transmissions(failed="all")) == 1
        assert len(net.transmissions(failed=True)) == 0
        assert len(net.transmissions(failed=False)) == 1
        assert len(net.transmissions(status="pending", failed="all")) == 0
        assert len(net.transmissions(status="received", failed="all")) == 1

        # test Network.transformations()
        assert len(net.transformations(failed="all")) == 1
        assert len(net.transformations(failed="all", type=Mutation)) == 0
        assert len(net.transformations(failed="all", type=models.Transformation)) == 1

        for t in net.transformations(failed="all"):
            assert isinstance(t.node, Agent)

        # test latest_transmission_recipient
        assert net.latest_transmission_recipient() == agent

        # test Network.vectors()
        assert len(net.vectors(failed="all")) == 3
        assert len(net.vectors(failed=False)) == 3
        assert len(net.vectors(failed=True)) == 0

        # test fail()
        net.fail()
        assert net.nodes() == []
        assert len(net.nodes(failed=True)) == 3
        assert len(net.nodes(failed="all")) == 3
        assert net.infos() == []
        assert net.transmissions() == []
        assert net.vectors() == []
        assert net.transformations() == []

        print("Testing models: Network    passed!")
        sys.stdout.flush()

    ##################################################################
    # Node
    ##################################################################

    def test_create_node(self, db_session):
        """Create a basic node"""
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        self.add(db_session, node)

        assert isinstance(node.id, int)
        assert node.type == "node"
        assert node.creation_time
        assert len(node.infos()) == 0
        assert len(node.vectors(direction="outgoing")) == 0
        assert len(node.vectors(direction="incoming")) == 0
        assert len(node.vectors(direction="outgoing")) == 0
        assert len(node.vectors(direction="incoming")) == 0

    def test_different_node_ids(self, db_session):
        """Test that two nodes have different ids"""
        net = models.Network()
        db_session.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(db_session, node1, node2)

        assert node1.id != node2.id

    def test_node_repr(self, db_session):
        """Test the repr of a node"""
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        self.add(db_session, node)

        assert repr(node).split("-") == ["Node", str(node.id), "node"]

    def _check_single_connection(self, node1, node2):
        assert node1.is_connected(direction="to", whom=node2)
        assert not node1.is_connected(direction="from", whom=node2)
        assert node2.is_connected(direction="from", whom=node1)
        assert not node2.is_connected(direction="to", whom=node2)

        vector = node1.vectors(direction="outgoing")[0]
        assert vector.origin_id == node1.id
        assert vector.destination_id == node2.id

        assert node1.vectors(direction="outgoing") == [vector]
        assert len(node1.vectors(direction="incoming")) == 0
        assert len(node2.vectors(direction="outgoing")) == 0
        assert node2.vectors(direction="incoming") == [vector]

        assert len(node1.vectors(direction="incoming")) == 0
        assert len(node1.vectors(direction="outgoing")) == 1
        assert len(node2.vectors(direction="incoming")) == 1
        assert len(node2.vectors(direction="outgoing")) == 0

        assert node1.neighbors(direction="to") == [node2]
        assert len(node1.neighbors(direction="from")) == 0
        assert node2.neighbors(direction="from") == [node1]
        assert len(node2.neighbors(direction="to")) == 0

    def test_node_connect(self, db_session):
        """Test connecting one node to another"""
        net = models.Network()
        db_session.add(net)
        db_session.commit()

        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        node3 = models.Node(network=net)
        node4 = models.Node(network=net)

        node1.connect(whom=node2)

        assert node1.neighbors(direction="to") == [node2]

        assert node2.neighbors(direction="from") == [node1]

        node2.connect(whom=[node3, node4])

        for n in node2.neighbors(direction="to"):
            assert n in [node3, node4]
        assert node3.neighbors(direction="from") == [node2]

        raises(ValueError, node1.connect, whom=node1)

        net = models.Network()
        self.add(db_session, net)

        raises(TypeError, node1.connect, whom=net)

    def test_node_outdegree(self, db_session):
        net = models.Network()
        self.add(db_session, net)
        node1 = models.Node(network=net)
        db_session.add(node1)

        for i in range(5):
            assert len(node1.vectors(direction="outgoing")) == i
            new_node = models.Node(network=net)
            self.add(db_session, new_node)
            db_session.commit()
            node1.connect(whom=new_node)
            self.add(db_session, new_node)

        assert len(node1.vectors(direction="outgoing")) == 5

        nodes = db_session.query(models.Node).all()

        node5 = [n for n in nodes if len(n.vectors(direction="outgoing")) == 5][0]
        assert node5 == node1

    def test_node_indegree(self, db_session):
        net = models.Network()
        self.add(db_session, net)
        node1 = models.Node(network=net)
        db_session.add(node1)
        db_session.commit()

        for i in range(5):
            assert len(node1.vectors(direction="incoming")) == i
            new_node = models.Node(network=net)
            db_session.add(new_node)
            db_session.commit()
            node1.connect(direction="from", whom=new_node)
            self.add(db_session, new_node)

        assert len(node1.vectors(direction="incoming")) == 5

        nodes = db_session.query(models.Node).all()
        node5 = [n for n in nodes if len(n.vectors(direction="incoming")) == 5][0]
        assert node5 == node1

    def test_node_has_connection_to(self, db_session):
        net = models.Network()
        self.add(db_session, net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(db_session, node1, node2)
        db_session.commit()

        node1.connect(whom=node2)
        self.add(db_session, node1, node2)

        assert node1.is_connected(direction="to", whom=node2)
        assert not node2.is_connected(direction="to", whom=node1)

    def test_node_has_connection_from(self, db_session):
        net = models.Network()
        self.add(db_session, net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(db_session, node1, node2)
        db_session.commit()

        node1.connect(whom=node2)
        self.add(db_session, node1, node2)

        assert not node1.is_connected(direction="from", whom=node2)
        assert node2.is_connected(direction="from", whom=node1)

    ##################################################################
    # Vector
    ##################################################################

    def test_create_vector(self, db_session):
        """Test creating a vector between two nodes"""
        net = models.Network()
        db_session.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(db_session, node1, node2)
        db_session.commit()

        node1.connect(whom=node2)

        self._check_single_connection(node1, node2)
        # assert len(vector.transmissions) == 0

    def test_kill_vector(self, db_session):
        net = models.Network()
        db_session.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        vector = models.Vector(origin=node1, destination=node2)
        self.add(db_session, node1, node2, vector)

        assert vector.failed is False

        vector.fail()
        assert vector.failed is True

    def test_create_bidirectional_vectors(self, db_session):
        """Test creating a bidirectional connection between nodes"""
        net = models.Network()
        db_session.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(db_session, node1, node2, vector1, vector2)

        assert vector1.origin_id == node1.id
        assert vector1.destination_id == node2.id
        assert vector2.origin_id == node2.id
        assert vector2.destination_id == node1.id

        assert node1.vectors(direction="incoming") == [vector2]
        assert node1.vectors(direction="outgoing") == [vector1]
        assert node2.vectors(direction="incoming") == [vector1]
        assert node2.vectors(direction="outgoing") == [vector2]

        assert node1.is_connected(direction="to", whom=node2)
        assert node1.is_connected(direction="from", whom=node2)
        assert node2.is_connected(direction="to", whom=node1)
        assert node2.is_connected(direction="from", whom=node1)

        assert len(node1.vectors(direction="incoming")) == 1
        assert len(node2.vectors(direction="incoming")) == 1
        assert len(node1.vectors(direction="outgoing")) == 1
        assert len(node2.vectors(direction="outgoing")) == 1

        assert len(vector1.transmissions()) == 0
        assert len(vector2.transmissions()) == 0

    def test_vector_repr(self, db_session):
        """Test the repr of a vector"""
        net = models.Network()
        db_session.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        vector1 = models.Vector(origin=node1, destination=node2)
        vector2 = models.Vector(origin=node2, destination=node1)
        self.add(db_session, node1, node2, vector1, vector2)

        assert repr(vector1).split("-") == ["Vector", str(node1.id), str(node2.id)]
        assert repr(vector2).split("-") == ["Vector", str(node2.id), str(node1.id)]

    ##################################################################
    # Info
    ##################################################################

    def test_create_info(self, db_session):
        """Try creating an info"""
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        info = models.Info(origin=node, contents="foo")
        self.add(db_session, node, info)

        assert isinstance(info.id, int)
        assert info.type == "info"
        assert info.origin_id == node.id
        assert info.creation_time
        assert info.contents == "foo"
        assert len(info.transmissions()) == 0

        assert node.infos() == [info]

    def test_create_two_infos(self, db_session):
        """Try creating two infos"""
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        info1 = models.Info(origin=node, contents="bar")
        info2 = models.Info(origin=node, contents="foo")
        self.add(db_session, node, info1, info2)

        assert info1.id != info2.id
        assert info1.origin_id == info2.origin_id
        assert info1.creation_time != info2.creation_time
        assert info1.contents != info2.contents
        assert len(info1.transmissions()) == 0
        assert len(info2.transmissions()) == 0

        assert len(node.infos()) == 2
        assert info1 in node.infos()
        assert info2 in node.infos()

    def test_info_repr(self, db_session):
        """Check the info repr"""
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        info = models.Info(origin=node)
        self.add(db_session, info)

        assert repr(info).split("-") == ["Info", str(info.id), "info"]

    def test_info_write_twice(self, db_session):
        """Overwrite an info's contents."""
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        info = models.Info(origin=node, contents="foo")

        self.add(db_session, node, info)

        assert info.contents == "foo"
        with raises(ValueError):
            info.contents = "ofo"

    ##################################################################
    # Transmission
    ##################################################################

    def test_create_transmission(self, db_session):
        """Try creating a transmission"""
        net = models.Network()
        db_session.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(db_session, node1, node2)
        db_session.commit()
        node1.connect(whom=node2)

        info = models.Info(origin=node1)
        node1.transmit(what=node1.infos()[0], to_whom=node2)
        # transmission = models.Transmission(info=info, destination=node2)
        # self.add(db_session, node1, node2, vector, info, transmission)

        transmission = node1.transmissions()[0]
        vector = node1.vectors()[0]

        assert isinstance(transmission.id, int)
        assert transmission.info_id == info.id
        assert transmission.origin_id == vector.origin_id
        assert transmission.destination_id == vector.destination_id
        assert transmission.creation_time
        assert transmission.vector == vector
        assert vector.transmissions() == [transmission]

    def test_transmit_none_finds_all_infos(self, db_session):
        net = models.Network()
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent1.connect(whom=agent2)

        info1 = models.Info(origin=agent1, contents="foo")
        info2 = models.Info(origin=agent1, contents="bar")
        self.add(db_session, info1, info2)
        transmissions = agent1.transmit(what=None, to_whom=agent2)

        assert len(transmissions) == 2
        for t in transmissions:
            assert t.origin is agent1
            assert t.destination is agent2

    def test_transmit_to_class_finds_nodes_in_network(self, db_session):
        net = models.Network()
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent1.connect(whom=agent2)

        info1 = models.Info(origin=agent1, contents="foo")
        self.add(db_session, info1)
        transmissions = agent1.transmit(what=info1, to_whom=nodes.ReplicatorAgent)
        assert len(transmissions) == 1
        assert transmissions[0].origin is agent1
        assert transmissions[0].destination is agent2

    def test_transmit_raises_if_no_connection_to_destination(self, db_session):
        net1 = models.Network()
        net2 = models.Network()
        agent1 = nodes.ReplicatorAgent(network=net1)
        agent2 = nodes.ReplicatorAgent(network=net2)

        info1 = models.Info(origin=agent1, contents="foo")
        info2 = models.Info(origin=agent1, contents="bar")
        self.add(db_session, info1, info2)

        with raises(ValueError) as excinfo:
            agent1.transmit(what=None, to_whom=agent2)
            assert excinfo.match("cannot transmit to {}".format(agent2))

    def test_transmission_repr(self, db_session):
        net = models.Network()
        db_session.add(net)
        node1 = models.Node(network=net)
        node2 = models.Node(network=net)
        self.add(db_session, node1, node2)

        node1.connect(whom=node2)
        models.Info(origin=node1)

        node1.transmit(what=node1.infos()[0], to_whom=node2)
        transmission = node1.transmissions()[0]
        node1.vectors()[0]

        assert repr(transmission).split("-") == ["Transmission", str(transmission.id)]

    def test_node_incoming_transmissions(self, db_session):
        net = models.Network()
        db_session.add(net)
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)
        self.add(db_session, agent1, agent2, agent3)
        db_session.commit()

        agent1.connect(direction="from", whom=[agent2, agent3])
        self.add(db_session, agent1, agent2, agent3)

        info1 = models.Info(origin=agent2, contents="foo")
        info2 = models.Info(origin=agent3, contents="bar")
        self.add(db_session, info1, info2)

        agent2.transmit(what=info1, to_whom=agent1)
        agent3.transmit(what=info2, to_whom=agent1)
        db_session.commit()

        assert len(agent1.transmissions(direction="incoming")) == 2
        assert len(agent2.transmissions(direction="incoming")) == 0
        assert len(agent3.transmissions(direction="incoming")) == 0

    def test_node_outgoing_transmissions(self, db_session):
        net = models.Network()
        db_session.add(net)
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)
        self.add(db_session, agent1, agent2, agent3)
        db_session.commit()

        agent1.connect(whom=agent2)
        agent1.connect(whom=agent3)
        self.add(db_session, agent1, agent2, agent3)

        info1 = models.Info(origin=agent1, contents="foo")
        info2 = models.Info(origin=agent1, contents="bar")
        self.add(db_session, info1, info2)

        agent1.transmit(what=info1, to_whom=agent2)
        agent1.transmit(what=info2, to_whom=agent3)
        db_session.commit()

        assert len(agent1.transmissions(direction="outgoing")) == 2
        assert len(agent2.transmissions(direction="outgoing")) == 0
        assert len(agent3.transmissions(direction="outgoing")) == 0

    def test_transmission_order(self, db_session):
        net = models.Network()
        db_session.add(net)
        agent1 = nodes.ReplicatorAgent(network=net)
        agent2 = nodes.ReplicatorAgent(network=net)
        agent3 = nodes.ReplicatorAgent(network=net)
        self.add(db_session, agent1, agent2, agent3)
        db_session.commit()

        agent1.connect(whom=agent2)
        agent1.connect(whom=agent3)
        self.add(db_session, agent1, agent2, agent3)

        info1 = models.Info(origin=agent1, contents="foo")
        info2 = models.Info(origin=agent1, contents="bar")
        info3 = models.Info(origin=agent1, contents="baz")
        info4 = models.Info(origin=agent1, contents="spam")
        self.add(db_session, info1, info2, info3, info4)

        agent1.transmit(what=info1, to_whom=agent2)
        agent2.receive()
        agent1.transmit(what=info2, to_whom=agent3)
        agent3.receive()
        agent1.transmit(what=info3, to_whom=agent2)
        agent2.receive()
        agent1.transmit(what=info4, to_whom=agent3)
        agent3.receive()
        db_session.commit()

        transmissions = agent1.transmissions()
        assert len(transmissions) == 4
        assert transmissions[0].receive_time < transmissions[1].receive_time
        assert transmissions[1].receive_time < transmissions[2].receive_time
        assert transmissions[2].receive_time < transmissions[3].receive_time

    def test_property_node(self, db_session):
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        node.property1 = "foo"
        self.add(db_session, node)

        assert node.property1 == "foo"

    def test_creation_time(self, db_session):
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        self.add(db_session, node)
        assert node.creation_time is not None

    def test_details(self, db_session):
        net = models.Network()
        db_session.add(net)
        node = models.Node(network=net)
        node.details = {"my_data": [1, 2, 3]}
        self.add(db_session, node)
        assert tuple(node.details["my_data"]) == (1, 2, 3)

    ##################################################################
    # Participant
    ##################################################################

    def test_create_participant(self, db_session):
        participant = models.Participant(
            recruiter_id="hotair",
            worker_id=str(1),
            hit_id=str(1),
            assignment_id=str(1),
            mode="test",
        )
        db_session.add(participant)
        db_session.commit()

        assert isinstance(participant.id, int)
        assert participant.type == "participant"

    def test_fail_participant(self, db_session):
        net = models.Network()
        db_session.add(net)
        participant = models.Participant(
            recruiter_id="hotair",
            worker_id=str(1),
            hit_id=str(1),
            assignment_id=str(1),
            mode="test",
        )
        db_session.add(participant)
        db_session.commit()
        node = models.Node(network=net, participant=participant)
        db_session.add(node)
        question = models.Question(
            participant=participant, number=1, question="what?", response="???"
        )
        db_session.add(question)

        assert len(participant.nodes()) == 1
        assert len(participant.questions()) == 1
        assert participant.failed is False

        participant.fail()

        assert participant.failed is True
        assert len(participant.nodes()) == 0
        assert len(participant.nodes(failed=True)) == 1
        assert len(participant.questions()) == 1
        assert participant.questions()[0].failed is True

    def test_fail_participant_captures_cascade_in_failure_reason(self, a):
        net = a.network()
        participant = a.participant()
        node = a.node(network=net, participant=participant)
        question = a.question(participant=participant)

        participant.fail("Boom!")

        assert participant.failed_reason == "Boom!"
        assert node.failed_reason == "Boom!->Participant1"
        assert question.failed_reason == "Boom!->Participant1"

    def test_participant_json(self, db_session):
        participant = models.Participant(
            recruiter_id="hotair",
            worker_id=str(1),
            hit_id=str(1),
            assignment_id=str(1),
            mode="test",
        )
        participant.details = {"data": "something"}
        db_session.add(participant)
        db_session.commit()

        participant_json = participant.__json__()
        assert "details" in participant_json
        assert participant_json["details"].get("data") == "something"

        # make sure private data is not in there
        assert "unique_id" not in participant_json
        assert "worker_id" not in participant_json

    def test_get_all_mapped_classes(self, db_session):
        net = models.Network()
        participant = models.Participant(
            recruiter_id="hotair",
            worker_id=str(1),
            hit_id=str(1),
            assignment_id=str(1),
            mode="test",
        )

        db_session.add(net)
        db_session.add(participant)
        db_session.commit()

        node = models.Node(network=net)
        agent = Agent(network=net, participant=participant)
        source = Source(network=net)

        db_session.add(node)
        db_session.add(agent)
        db_session.add(source)
        db_session.commit()

        classes = get_all_mapped_classes()

        assert classes["Participant"] == {
            "cls": models.Participant,
            "table": "participant",
            "polymorphic_identity": "participant",
        }

        assert classes["Source"] == {
            "cls": Source,
            "table": "node",
            "polymorphic_identity": "generic_source",
        }

        assert classes["Agent"] == {
            "cls": Agent,
            "table": "node",
            "polymorphic_identity": "agent",
        }

        assert classes["Node"] == {
            "cls": models.Node,
            "table": "node",
            "polymorphic_identity": "node",
        }

    def test_get_polymorphic_mapping(self, db_session):
        table = Base.metadata.tables["node"]
        mappers = get_polymorphic_mapping(table)

        assert mappers["generic_source"] == Source
        assert mappers["agent"] == Agent
        assert mappers["node"] == models.Node
