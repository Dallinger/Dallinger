from uuid import uuid4
from datetime import datetime

# get the connection to the database
from .db import Base

# various sqlalchemy imports
from sqlalchemy import ForeignKey, desc, or_
from sqlalchemy import Column, String, Text, Enum, Float, Integer
from sqlalchemy.orm import relationship, validates
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func, select
from sqlalchemy.ext.associationproxy import association_proxy

import inspect

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def new_uuid():
    return uuid4().hex


def timenow():
    time = datetime.now()
    return time.strftime(DATETIME_FMT)


class Node(Base):
    __tablename__ = "node"

    # the unique node id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the node type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the time when the node was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    # the status of the node
    status = Column(Enum("alive", "dead", "failed", name="node_status"),
                    nullable=False, default="alive")

    # the time when the node changed from alive->dead or alive->failed
    time_of_death = Column(String(26), nullable=True, default=None)

    # the information created by this node
    information = relationship(
        "Info", backref='origin', order_by="Info.creation_time")

    # the network that this node is a part of
    network_uuid = Column(
        String(32), ForeignKey('network.uuid'), nullable=True)

    # the participant uuid is the sha512 hash of the psiTurk uniqueId of the
    # participant who was this node.
    participant_uuid = Column(String(128), nullable=True)

    network = relationship("Network", foreign_keys=[network_uuid])

    def die(self):
        if self.status == "dead":
            raise AttributeError("You cannot kill {} - it is already dead.".format(self))
        else:
            self.status = "dead"
            self.time_of_death = timenow()
            for v in self.vectors(direction="incoming"):
                v.die()
            for v in self.vectors(direction="outgoing"):
                v.die()
            for i in self.infos():
                i.die()
            for t in self.transmissions(direction="incoming", state="all"):
                t.die()
            for t in self.transmissions(direction="outgoing", state="all"):
                t.die()

    def fail(self):
        if self.status == "failed":
            raise AttributeError("You cannot fail {} - it has already failed.".format(self))
        else:
            self.status = "failed"
            self.time_of_death = timenow()
            for v in self.vectors(direction="incoming"):
                v.fail()
            for v in self.vectors(direction="outgoing"):
                v.fail()
            for i in self.infos():
                i.fail()
            for t in self.transmissions(direction="incoming", state="all"):
                t.fail()
            for t in self.transmissions(direction="outgoing", state="all"):
                t.fail()

    def vectors(self, direction="all", status="alive"):
        if direction not in ["all", "incoming", "outgoing"]:
            raise ValueError("{} is not a valid vector direction. Must be all, incoming or outgoing.".format(direction))
        if status not in ["alive", "dead", "failed"]:
            raise Warning("Warning, possible typo: {} is not a standard vector status".format(status))
        if direction == "all":
            if status == "all":
                return Vector.query\
                    .filter_by(or_(destination=self, origin=self))\
                    .all()
            else:
                return Vector.query\
                    .filter_by(or_(destination=self, origin=self))\
                    .filter_by(status=status)\
                    .all()
        elif direction == "incoming":
            if status == "all":
                return Vector.query\
                    .filter_by(destination=self)\
                    .all()
            else:
                return Vector.query\
                    .filter_by(destination=self)\
                    .filter_by(status=status)\
                    .all()
        elif direction == "outgoing":
            if status == "all":
                return Vector.query\
                    .filter_by(origin=self)\
                    .all()
            else:
                return Vector.query\
                    .filter_by(origin=self)\
                    .filter_by(status=status)\
                    .all()

    def downstream_nodes(self, type=None, status="alive"):
        """
        Get all nodes of given type that this node connects to.
        If status is alive/dead/failed, looks for nodes of that status along
        vectors of that status (i.e., dead nodes at the end of dead vectors).
        """
        if type is None:
            type = Node
        if status in ["alive", "dead", "failed"]:
            return [v.destination for v in self.vectors(direction="outgoing", status=status)
                    if isinstance(v.destination, type) and v.destination.status == status]
        else:
            raise(ValueError("Cannot get downstream_nodes with status {} as it is not a valid status.".format(status)))

    def upstream_nodes(self, type=None, status="alive"):
        """
        Get all nodes of given type that connect to this node.
        If status is alive/dead/failed, looks for nodes of that status along
        vectors of that status (i.e., dead nodes at the end of dead vectors).
        """
        if type is None:
            type = Node
        if status in ["alive", "dead", "failed"]:
            return [v.origin for v in self.vectors(direction="incoming", status=status)
                    if isinstance(v.origin, type) and v.origin.status == status]
        else:
            raise(ValueError("Cannot get_upstream_nodes with status {} as it is not a valid status.".format(status)))

    def infos(self, type=None, status="alive"):
        """
        Get infos that originated at this node.
        By passing status as an argument you can get alive/dead/failed infos.
        Status defaults to alive.
        """

        if type is None:
            type = Info
        if not issubclass(type, Info):
            raise(TypeError("Cannot get-info of type {} as it is not a valid type.".format(type)))
        else:
            return type\
                .query\
                .order_by(type.creation_time)\
                .filter(type.origin == self)\
                .filter_by(status=status)\
                .all()

    def __repr__(self):
        return "Node-{}-{}".format(self.uuid[:6], self.type)

    def connect_to(self, other_node):
        """Creates a vector from self to other_node.
        other_node may be a list of nodes.
        Will raise an error if:
        (1) other_node is not a node or list of nodes
        (2) other_node is a source
        (3) other_node is not alive
        (4) other_node is yourself
        (5) other_node is in a different network
        If self is already connected to other_node a Warning
        is raised and nothing happens.
        """

        if not isinstance(other_node, Node):
            if isinstance(other_node, list):
                for node in other_node:
                    self.connect_to(node)
            else:
                raise(TypeError('{} cannot connect to {} as it is a {}'.format(self, other_node, type(other_node))))
        elif isinstance(other_node, Source):
            raise(TypeError("{} cannot connect_to {} as it is a Source.".format(self, other_node)))
        elif other_node.status != "alive":
            raise(ValueError("{} cannot connect to {} as it is {}".format(self, other_node, other_node.status)))
        elif self == other_node:
            raise(ValueError("{} cannot connect to itself.".format(self)))
        elif self.network_uuid != other_node.network_uuid:
            raise(ValueError(("{} cannot connect to {} as they are not " +
                              "in the same network. {} is in network {}, " +
                              "but {} is in network {}.")
                             .format(self, other_node, self, self.network_uuid,
                                     other_node, other_node.network_uuid)))
        else:
            if self.has_connection_to(other_node):
                print "Warning! {} is already connected to {}, cannot make another vector without killing the old one.".format(self, other_node)
            else:
                Vector(origin=self, destination=other_node, network=self.network)

    def connect_from(self, other_node):
        """Creates a directed edge from other_node to self
        other_node may be a list of nodes
        will raise an error if you try to connect_from anything other than a node"""
        if isinstance(other_node, list):
            for node in other_node:
                node.connect_to(self)
        else:
            other_node.connect_to(self)

    def transmit(self, what=None, to_whom=None):
        """
        Transmit what to whom.

        Will work provided what is an Info or a class of Info, or a list
        containing the two. If what=None the _what() method is called to
        generate what. Will work provided to_whom is a Node you are connected
        to or a class of Nodes, or a list containing the two. If to_whom=None
        the _to_whom() method is called to generate to_whom.
        """

        if what is None:
            what = self._what()
            if what is None or (isinstance(what, list) and None in what):
                raise ValueError("The _what() of {} is returning None."
                                 .format(self))
            else:
                self.transmit(what=what, to_whom=to_whom)
        elif isinstance(what, list):
            for w in what:
                self.transmit(what=w, to_whom=to_whom)
        elif inspect.isclass(what) and issubclass(what, Info):
            infos = what\
                .query\
                .filter_by(origin_uuid=self.uuid)\
                .order_by(desc(Info.creation_time))\
                .all()
            self.transmit(what=infos, to_whom=to_whom)
        elif isinstance(what, Info):

            # Check if sender owns the info.
            if what.origin_uuid != self.uuid:
                raise ValueError(
                    "{} cannot transmit {} because it is not its origin"
                    .format(self, what))

            if to_whom is None:
                to_whom = self._to_whom()
                if to_whom is None or (
                   isinstance(to_whom, list) and None in to_whom):
                    raise ValueError("the _to_whom() of {} is returning None."
                                     .format(self))
                else:
                    self.transmit(what=what, to_whom=to_whom)
            elif isinstance(to_whom, list):
                for w in to_whom:
                    self.transmit(what=what, to_whom=w)
            elif inspect.isclass(to_whom) and issubclass(to_whom, Node):
                to_whom = [w for w in self.downstream_nodes(type=to_whom)]
                self.transmit(what=what, to_whom=to_whom)
            elif isinstance(to_whom, Node):
                if not self.has_connection_to(to_whom):
                    raise ValueError(
                        "Cannot transmit from {} to {}: " +
                        "they are not connected".format(self, to_whom))
                else:
                    t = Transmission(info=what, destination=to_whom)
                    what.transmissions.append(t)
            else:
                raise TypeError("Cannot transmit to '{}': ",
                                 "it is not a Node".format(to_whom))
        else:
            raise TypeError("Cannot transmit '{}': it is not an Info"
                             .format(what))

    def _what(self):
        return Info

    def _to_whom(self):
        return Node

    def observe(self, environment):
        state = environment.get_observed(by_whom=self)
        return state

    def update(self, infos):
        raise NotImplementedError(
            "The update method of node '{}' has not been overridden"
            .format(self))

    def receive_all(self):
        pending_transmissions = self.transmissions(direction="incoming", state="pending")
        for transmission in pending_transmissions:
            transmission.receive_time = timenow()
            transmission.mark_received()
        self.update([t.info for t in pending_transmissions])

    def receive(self, thing):
        if isinstance(thing, Transmission):
            if thing in self.transmissions(direction="incoming", state="pending"):
                thing.receive_time = timenow()
                thing.mark_received()
                self.update(thing.info)
            else:
                raise(ValueError("{} cannot receive {} as it is not in its pending_transmissions".format(self, thing)))
        elif isinstance(thing, Info):
            relevant_transmissions = []
            for transmission in self.transmissions(direction="incoming", state="pending"):
                if transmission.info == thing:
                    relevant_transmissions.append(transmission)
            if (len(relevant_transmissions) > 0):
                for transmission in relevant_transmissions:
                    transmission.receive_time = timenow()
                    transmission.mark_received()
                self.update([t.info for t in relevant_transmissions])
            else:
                raise(ValueError("{} cannot receive {} as it is not in its pending_transmissions".format(self, thing)))

    @hybrid_property
    def outdegree(self):
        """The outdegree (number of outgoing edges) of this node."""
        return len(self.vectors(direction="outgoing"))

    @outdegree.expression
    def outdegree(self):
        return select([func.count(Vector.destination_uuid)])\
            .where(Vector.origin_uuid == Node.uuid)\
            .label("outdegree")

    @hybrid_property
    def indegree(self):
        """The indegree (number of incoming edges) of this node."""
        return len(self.vectors(direction="incoming"))

    @indegree.expression
    def indegree(self):
        return select([func.count(Vector.origin_uuid)])\
            .where(Vector.destination_uuid == Node.uuid)\
            .label("indegree")

    def has_connection_to(self, other_node):
        """Whether this node has a connection to 'other_node'. Can take a list
        of nodes. If passed a list returns a list of booleans."""
        if isinstance(other_node, list):
            return [self.has_connection_to(n) for n in other_node]
        elif isinstance(other_node, Node):
            return other_node in self.downstream_nodes()
        else:
            raise(TypeError("Cannot check if {} is connected to {} as {} is not a Node, it is a {}".
                  format(self, other_node, other_node, type(other_node))))

    def has_connection_from(self, other_node):
        """Whether this node has a connection from 'other_node'.
        Can take a list of nodes. If passed a list returns a list
        of booleans."""
        if isinstance(other_node, list):
            return [n.has_connection_to(self) for n in list]
        else:
            return other_node.has_connection_to(self)

    def transmissions(self, direction=None, state="all", status="alive"):
        if direction is None:
            raise(ValueError("You cannot get transmissions without specifying the type of transmission you want" +
                  "It should be incoming, outgoing or all"))
        if direction not in ["incoming", "outgoing", "all"]:
            raise(ValueError("You cannot get transmissions of type {}.".format(type) +
                  "Type can only be incoming, outgoing or all."))
        if state not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get transmission of status {}.".format(status) +
                  "Status can only be pending, received or all"))
        if direction == "incoming":
            if state == "all":
                return Transmission\
                    .query\
                    .filter_by(destination_uuid=self.uuid)\
                    .filter_by(status="alive")\
                    .order_by(Transmission.transmit_time)\
                    .all()
            elif state == "pending":
                return Transmission\
                    .query\
                    .filter_by(destination_uuid=self.uuid)\
                    .filter_by(status="alive")\
                    .filter(Transmission.receive_time == None)\
                    .order_by(Transmission.transmit_time)\
                    .all()
            elif state == "received":
                return Transmission\
                    .query\
                    .filter_by(destination_uuid=self.uuid)\
                    .filter_by(status="alive")\
                    .filter(Transmission.receive_time != None)\
                    .order_by(Transmission.transmit_time)\
                    .all()
        elif direction == "outgoing":
            if state == "all":
                return Transmission\
                    .query\
                    .filter_by(origin_uuid=self.uuid)\
                    .filter_by(status="alive")\
                    .order_by(Transmission.transmit_time)\
                    .all()
            elif state == "pending":
                return Transmission\
                    .query\
                    .filter_by(origin_uuid=self.uuid)\
                    .filter_by(status="alive")\
                    .filter(Transmission.receive_time == None)\
                    .order_by(Transmission.transmit_time)\
                    .all()
            elif state == "received":
                return Transmission\
                    .query\
                    .filter_by(origin_uuid=self.uuid)\
                    .filter_by(status="alive")\
                    .filter(Transmission.receive_time != None)\
                    .order_by(Transmission.transmit_time)\
                    .all()
        elif direction == "all":
            if state == "all":
                return Transmission\
                    .query\
                    .filter_by(status="alive")\
                    .order_by(Transmission.transmit_time)\
                    .all()
            elif state == "pending":
                return Transmission\
                    .query\
                    .filter(Transmission.receive_time == None)\
                    .filter_by(status="alive")\
                    .order_by(Transmission.transmit_time)\
                    .all()
            elif state == "received":
                return Transmission\
                    .query\
                    .filter(Transmission.receive_time != None)\
                    .filter_by(status="alive")\
                    .order_by(Transmission.transmit_time)\
                    .all()
        else:
            raise(Exception("The arguments passed to transmissions() did not cause an error," +
                  " but also did not cause the method to run properly. This needs to be fixed asap." +
                  "status: {}, type: {}".format(status, type)))


class Agent(Node):

    """Agents have genomes and memomes, and update their contents when faced.
    By default, agents transmit unadulterated copies of their genomes and
    memomes, with no error or mutation.
    """

    __tablename__ = "agent"
    __mapper_args__ = {"polymorphic_identity": "agent"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)
    fitness = Column(Float, nullable=True, default=None)

    def _selector(self):
        raise DeprecationWarning(
            "_selector is deprecated - ",
            "use _what() instead.")

    def update(self, infos):
        raise NotImplementedError(
            "You have not overridden the update method in {}"
            .format(type(self)))

    def calculate_fitness(self):
        raise NotImplementedError(
            "You have not overridden the calculate_fitness method in {}"
            .format(type(self)))

    def replicate(self, info_in):
        """Create a new info of the same type as the incoming info."""
        info_type = type(info_in)
        info_out = info_type(origin=self, contents=info_in.contents)

        # Register the transformation.
        from .transformations import Replication
        Replication(info_out=info_out, info_in=info_in, node=self)


class Source(Node):
    __tablename__ = "source"
    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    def create_information(self):
        """Generate new information."""
        raise NotImplementedError(
            "{} cannot create_information as it does not override ",
            "the default method.".format(type(self)))

    def _what(self):
        return self.create_information()


class Vector(Base):
    __tablename__ = "vector"

    # the unique vector id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the origin node
    origin_uuid = Column(String(32), ForeignKey('node.uuid'))
    origin = relationship(
        Node, foreign_keys=[origin_uuid],
        backref="all_outgoing_vectors")

    # the destination node
    destination_uuid = Column(
        String(32), ForeignKey('node.uuid'))
    destination = relationship(
        Node, foreign_keys=[destination_uuid],
        backref="all_incoming_vectors")

    # the status of the vector
    status = Column(Enum("alive", "dead", "failed", name="vector_status"),
                    nullable=False, default="alive")

    # the time when the vector changed from alive->dead
    time_of_death = Column(
        String(26), nullable=True, default=None)

    network_uuid = association_proxy('origin', 'network_uuid')

    network = association_proxy('origin', 'network')

    def die(self):
        if self.status == "dead":
            raise AttributeError("You cannot kill {}, it is already dead.".format(self))
        else:
            self.status = "dead"
            self.time_of_death = timenow()

    def fail(self):
        if self.status == "failed":
            raise AttributeError("You cannot fail {}, it has already failed".format(self))
        else:
            self.status = "failed"
            self.time_of_death = timenow()

    def __repr__(self):
        return "Vector-{}-{}".format(
            self.origin_uuid[:6], self.destination_uuid[:6])

    @property
    def transmissions(self):
        return Transmission\
            .query\
            .filter_by(
                origin_uuid=self.origin_uuid,
                destination_uuid=self.destination_uuid)\
            .order_by(Transmission.transmit_time)\
            .all()


class Network(Base):

    """A network of nodes."""

    __tablename__ = "network"

    # the unique network id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the network type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the time when the node was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    max_size = Column(Integer, nullable=False, default=1e6)

    role = Column(String(26), nullable=False, default="default")

    def nodes(self, type=Node, status="alive"):
        if not issubclass(type, Node):
            raise(TypeError("Cannot get nodes of type {} as it is not a valid type.".format(type)))
        if status == "alive" or status == "dead" or status == "failed":
            return type\
                .query\
                .order_by(type.creation_time)\
                .filter(type.status == status)\
                .filter(type.network == self)\
                .all()
        elif status == "all":
            return type\
                .query\
                .order_by(type.creation_time)\
                .filter(type.network == self)\
                .all()
        else:
            raise(ValueError("Cannot get nodes with status {} as it is not a valid status.".format(status)))

    def nodes_of_participant(self, participant_uuid):
        return Node\
            .query\
            .filter_by(network=self)\
            .filter_by(participant_uuid=participant_uuid)\
            .all()

    def transmissions(self, state="all", status="alive"):
        if state not in ["all", "pending", "received"]:
            raise(ValueError("You cannot get transmission of status {}.".format(status) +
                  "Status can only be pending, received or all"))
        elif state == "all":
            return Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .filter_by(status=status)\
                .order_by(Transmission.transmit_time)\
                .all()
        elif state == "received":
            return Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .filter_by(status=status)\
                .filter(Transmission.receive_time != None)\
                .order_by(Transmission.transmit_time)\
                .all()
        elif state == "pending":
            return Transmission\
                .query\
                .filter_by(network_uuid=self.uuid)\
                .filter_by(status=status)\
                .filter_by(receive_time=None)\
                .order_by(Transmission.transmit_time)\
                .all()
        else:
            raise(Exception("The arguments passed to transmissions() did not cause an error," +
                  " but also did not cause the method to run properly. This needs to be fixed asap." +
                  "status: {}, type: {}".format(status, type)))

    def latest_transmission_recipient(self):
        received_transmissions = reversed(self.transmissions(state="received"))
        return next(
            (t.destination for t in received_transmissions
                if (t.destination.status != "failed")),
            None)

    vectors = relationship(
        "Vector",
        secondary=Node.__table__,
        primaryjoin="Network.uuid==Node.network_uuid",
        secondaryjoin="Node.uuid==Vector.origin_uuid",
    )

    def full(self):
        return len(self.nodes(type=Agent)) >= self.max_size

    @property
    def degrees(self):
        return [agent.outdegree for agent in self.nodes(type=Agent)]

    def add(self, base):
        if isinstance(base, list):
            for b in base:
                self.add(b)
        elif isinstance(base, Node):
            base.network = self
        else:
            raise(TypeError("Cannot add {} to the network as it is a {}. " +
                            "Only Nodes can be added to networks.").format(base, type(base)))

    def __len__(self):
        raise SyntaxError(
            "len is not defined for networks. " +
            "Use len(net.nodes()) instead.")

    def __repr__(self):
        return "<Network-{}-{} with {} agents, {} sources, {} vectors>".format(
            self.uuid[:6],
            self.type,
            len(self.nodes(type=Agent)),
            len(self.nodes(type=Source)),
            len(self.vectors))

    def print_verbose(self):
        print "Agents: "
        for a in self.nodes(type=Agent):
            print a

        print "\nSources: "
        for s in self.nodes(type=Source):
            print s

        print "\nVectors: "
        for v in self.vectors:
            print v

    def has_participant(self, participant_uuid):
        nodes = Node.query\
            .filter_by(participant_uuid=participant_uuid)\
            .filter_by(network=self).all()

        return any(nodes)


class Info(Base):
    __tablename__ = "info"

    # the unique info id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the info type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the node that created this info
    origin_uuid = Column(String(32), ForeignKey('node.uuid'), nullable=False)

    # the time when the info was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    network_uuid = association_proxy('origin', 'network_uuid')

    network = association_proxy('origin', 'network')

    # the status of the info
    status = Column(Enum("alive", "dead", "failed", name="info_status"),
                    nullable=False, default="alive")

    # the contents of the info
    contents = Column(Text())

    @validates("contents")
    def _write_once(self, key, value):
        existing = getattr(self, key)
        if existing is not None:
            raise ValueError("The contents of an info is write-once.")
        return value

    def __repr__(self):
        return "Info-{}-{}".format(self.uuid[:6], self.type)

    def die(self):
        if self.status == "dead":
            raise AttributeError("You cannot kill {} - it is already dead.".format(self))
        else:
            self.status = "dead"
            self.time_of_death = timenow()

    def fail(self):
        if self.status == "failed":
            raise AttributeError("You cannot fail {} - it has already failed.".format(self))
        else:
            self.status = "failed"
            self.time_of_death = timenow()


class Transmission(Base):
    __tablename__ = "transmission"

    # the unique transmission id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the info that was transmitted
    info_uuid = Column(String(32), ForeignKey('info.uuid'), nullable=False)
    info = relationship(Info, backref='transmissions')

    # the time at which the transmission occurred
    transmit_time = Column(String(26), nullable=False, default=timenow)

    # the time at which the transmission was received
    receive_time = Column(String(26), nullable=True, default=None)

    # the origin of the info, which is proxied by association from the
    # info itself
    origin_uuid = association_proxy('info', 'origin_uuid')
    origin = association_proxy('info', 'origin')

    network_uuid = association_proxy('info', 'network_uuid')

    network = association_proxy('info', 'network')

    # the status of the transmission
    status = Column(Enum("alive", "dead", "failed", name="transmission_status"),
                    nullable=False, default="alive")

    # the destination of the info
    destination_uuid = Column(
        String(32), ForeignKey('node.uuid'), nullable=False)
    destination = relationship(Node, foreign_keys=[destination_uuid])

    def die(self):
        if self.status == "dead":
            raise AttributeError("You cannot kill {} - it is already dead.".format(self))
        else:
            self.status = "dead"
            self.time_of_death = timenow()

    def fail(self):
        if self.status == "failed":
            raise AttributeError("You cannot fail {} - it has already failed.".format(self))
        else:
            self.status = "failed"
            self.time_of_death = timenow()

    @property
    def vector(self):
        return Vector.query.filter_by(
            origin_uuid=self.origin_uuid,
            destination_uuid=self.destination_uuid).one()

    def mark_received(self):
        self.receive_time = timenow()

    def __repr__(self):
        return "Transmission-{}".format(self.uuid[:6])


class Transformation(Base):
    __tablename__ = "transformation"

    # the transformation type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the unique transformation id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the node that applied this transformation
    node_uuid = Column(String(32), ForeignKey('node.uuid'), nullable=False)
    node = relationship(Node, backref='transformations')

    network_uuid = association_proxy('node', 'network_uuid')

    network = association_proxy('node', 'network')

    # the info before it was transformed
    info_in_uuid = Column(String(32), ForeignKey('info.uuid'), nullable=False)
    info_in = relationship(
        Info,
        foreign_keys=[info_in_uuid],
        backref="transformation_applied_to")

    # the info produced as a result of the transformation
    info_out_uuid = Column(String(32), ForeignKey('info.uuid'), nullable=False)
    info_out = relationship(
        Info,
        foreign_keys=[info_out_uuid],
        backref="transformation_whence")

    # the time at which the transformation occurred
    transform_time = Column(String(26), nullable=False, default=timenow)

    def __repr__(self):
        return "Transformation-{}".format(self.uuid[:6])
