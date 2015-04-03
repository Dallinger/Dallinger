from uuid import uuid4
from datetime import datetime

# get the connection to the database
from .db import Base

# various sqlalchemy imports
from sqlalchemy import ForeignKey, desc
from sqlalchemy import Column, String, Text, Enum, Float
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

    def kill(self):
        self.status = "dead"
        self.time_of_death = timenow()

    def fail(self):
        self.status = "failed"
        self.time_of_death = timenow()

    # the predecessors and successors
    successors = relationship(
        "Node",
        secondary="vector",
        primaryjoin="Node.uuid==vector.c.origin_uuid",
        secondaryjoin="Node.uuid==vector.c.destination_uuid",
        backref="predecessors"
    )

    def get_incoming_vectors(self, status="alive"):
        if status == "all":
            incoming_vectors = Vector.query.filter_by(destination=self).all()
        elif status == "alive" or status == "dead":
            incoming_vectors = Vector.query.filter_by(destination=self).filter_by(status=status).all()
        else:
            raise(ValueError("Cannot get_incoming_vectors with status {} as it is not a valid status.".format(status)))
        return incoming_vectors

    def get_outgoing_vectors(self, status="alive"):
        if status == "all":
            outgoing_vectors = Vector.query.filter_by(origin=self).all()
        elif status == "alive" or status == "dead":
            outgoing_vectors = Vector.query.filter_by(origin=self).filter_by(status=status).all()
        else:
            raise(ValueError("Cannot get_outgoing_vectors with status {} as it is not a valid status.".format(status)))
        return outgoing_vectors

    def get_downstream_nodes(self, type=None, status="alive"):
        if type == None:
            type = Node
        if status == "all":
            return [v.destination for v in self.get_outgoing_vectors()
                if isinstance(v.destination, type)]
        elif status == "alive" or status == "dead" or status == "failed":
            return [v.destination for v in self.get_outgoing_vectors()
                if isinstance(v.destination, type) and v.destination.status == status]
        else:
            raise(ValueError("Cannot get_downstream_nodes with status {} as it is not a valid status.".format(status)))

    def get_upstream_nodes(self, type=None, status="alive"):
        if type == None:
            type = Node
        if status == "all":
            return [v.origin for v in self.get_incoming_vectors()
                if isinstance(v.origin, type)]
        elif status == "alive" or status == "dead" or status == "failed":
            return [v.origin for v in self.get_incoming_vectors()
                if isinstance(v.origin, type) and v.origin.status == status]
        else:
            raise(ValueError("Cannot get_upstream_nodes with status {} as it is not a valid status.".format(status)))

    def get_info(self, type=None):
        if type == None:
            type = Info
        if not issubclass(type, Info):
            raise(ValueError("Cannot get-info of type {} as it is not a valid type.".format(type)))
        else:
            return type\
                .query\
                .order_by(type.creation_time)\
                .filter(type.origin == self)\
                .all()

    @property
    def successors2(self):
        print "successors2 is deprecated, use get_downstream_nodes(type=Agent) instead"
        return self.get_downstream_nodes(type=Agent)

    @property
    def downstream_nodes(self):
        print "downstream_nodes is deprecated, use get_downstream_nodes() instead"
        return self.get_downstream_nodes()

    @property
    def downstream_agents(self):
        print "downstream_agents is deprecated, use get_downstream_nodes(type=Agent) instead"
        return self.get_downstream_nodes(type=Agent)

    @property
    def upstream_nodes(self):
        print "upstream_nodes is deprecated, use get_upstream_nodes() instead"
        return self.get_upstream_nodes()

    @property
    def upstream_agents(self):
        print "upstream_agents is deprecated, use get_upstream_nodes(type=Agent) instead"
        return self.get_upstream_nodes(type=Agent)

    @property
    def predecessors2(self):
        print "predecessors2 is deprecated, use get_upstream_nodes(type=Agent) instead"
        return self.get_upstream_nodes(type=Agent)

    def __repr__(self):
        return "Node-{}-{}".format(self.uuid[:6], self.type)

    def connect_to(self, other_node):
        """Creates a directed edge from self to other_node"""
        """other_node may be a list of nodes"""
        if isinstance(other_node, list) :
            for node in other_node:
                self.connect_to(node)
        elif self == other_node:
            raise(ValueError("{} cannot connect to itself.".format(self)))
        elif not isinstance(other_node, Node):
            raise(ValueError('{} cannot connect to {} as it is a {}'.format(self, other_node, type(other_node))))
        elif self.network_uuid != other_node.network_uuid:
            raise(ValueError(("{} cannot connect to {} as they are not " +
                              "in the same network. {} is in network {}, " +
                              "but {} is in network {}.")
                             .format(self, other_node, self, self.network_uuid,
                                     other_node, other_node.network_uuid)))
        else:
            Vector(origin=self, destination=other_node, network=self.network)
            #vector = Vector(origin=self, destination=other_node)
            #return vector

    def connect_from(self, other_node):
        """Creates a directed edge from other_node to self"""
        if isinstance(other_node, list) :
            for node in other_node:
                node.connect_to(self)
        else:
            other_node.connect_to(self)

    def transmit(self, what=None, to_whom=None):
        """Transmits what to whom. Will work provided what is an Info or a
        class of Info, or a list containing the two. If what=None the _what()
        method is called to generate what. Will work provided who is a Node you
        are connected to or a class of Nodes, or a list containing the two If
        to_whom=None the _to_whom() method is called to generate to_whom.
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
                    "Cannot transmit because {} is not the origin of {}"
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
                to_whom = [w for w in self.successors
                           if isinstance(w, to_whom)]
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
                raise ValueError("Cannot transmit to '{}': ",
                                 "it is not a Node".format(to_whom))
        else:
            raise ValueError("Cannot transmit '{}': it is not an Info"
                             .format(what))

    def _what(self):
        return Info

    def _to_whom(self):
        return Node

    def observe(self, environment):
        environment.get_observed(by_whom=self)

    def update(self, infos):
        raise NotImplementedError(
            "The update method of node '{}' has not been overridden"
            .format(self))

    def receive_all(self):
        pending_transmissions = self.pending_transmissions
        for transmission in pending_transmissions:
            transmission.receive_time = timenow()
            transmission.mark_received()
        self.update([t.info for t in pending_transmissions])

    @hybrid_property
    def outdegree(self):
        """The outdegree (number of outgoing edges) of this node."""
        # return len(self.outgoing_vectors)
        return len(Vector.query.filter_by(origin=self).all())

    @outdegree.expression
    def outdegree(self):
        return select([func.count(Vector.destination_uuid)])\
            .where(Vector.origin_uuid == Node.uuid)\
            .label("outdegree")

    @hybrid_property
    def indegree(self):
        """The indegree (number of incoming edges) of this node."""
        return len(self.incoming_vectors)

    @indegree.expression
    def indegree(self):
        return select([func.count(Vector.origin_uuid)])\
            .where(Vector.destination_uuid == Node.uuid)\
            .label("indegree")

    def has_connection_to(self, other_node):
        """Whether this node has a connection to 'other_node'."""
        # return other_node in self.successors
        return other_node in self.downstream_nodes

    def has_connection_from(self, other_node):
        """Whether this node has a connection from 'other_node'."""
        return other_node in self.upstream_nodes

    @property
    def incoming_transmissions(self):
        return Transmission\
            .query\
            .filter_by(destination_uuid=self.uuid)\
            .order_by(Transmission.transmit_time)\
            .all()

    @property
    def outgoing_transmissions(self):
        return Transmission\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(Transmission.transmit_time)\
            .all()

    @property
    def pending_transmissions(self):
        return Transmission\
            .query\
            .filter_by(destination_uuid=self.uuid)\
            .filter_by(receive_time=None)\
            .order_by(Transmission.transmit_time)\
            .all()

    @property
    def information_of_type(self, type=None):
        if not type:
            type = Info

        return type\
            .query\
            .filter_by(origin=self)\
            .order_by(Info.creation_time)\
            .all()


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
        raise NotImplementedError(
            "_selector is deprecated and needs to be overridden - ",
            "use _what() instead and remember to override it.")

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


class Vector(Base):
    __tablename__ = "vector"

    # the unique vector id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the origin node
    origin_uuid = Column(String(32), ForeignKey('node.uuid'))
    origin = relationship(
        Node, foreign_keys=[origin_uuid],
        backref="outgoing_vectors")

    # the destination node
    destination_uuid = Column(
        String(32), ForeignKey('node.uuid'))
    destination = relationship(
        Node, foreign_keys=[destination_uuid],
        backref="incoming_vectors")

    # the status of the vector
    status = Column(Enum("alive", "dead", name="vector_status"),
                    nullable=False, default="alive")

    # the time when the vector changed from alive->dead
    time_of_death = Column(
        String(26), nullable=True, default=None)

    network_uuid = association_proxy('origin', 'network_uuid')

    network = association_proxy('origin', 'network')

    def kill(self):
        self.status = "dead"
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

    # the node type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the time when the node was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    @property
    def agents(self):
        return Agent\
            .query\
            .order_by(Agent.creation_time)\
            .filter(Agent.status != "failed")\
            .filter(Agent.network == self)\
            .filter(Agent.status != "dead")\
            .all()

    @property
    def sources(self):
        return Source\
            .query\
            .order_by(Source.creation_time)\
            .filter(Source.network == self)\
            .all()

    @property
    def nodes(self):
        return self.sources + self.agents

    @property
    def vectors(self):
        return Vector\
            .query\
            .order_by(Vector.origin_uuid, Vector.destination_uuid)\
            .filter(Vector.network == self)\
            .all()

    @property
    def degrees(self):
        return [agent.outdegree for agent in self.agents]

    def add(self, base):
        base.network = self

    def add_source(self, source):
        source.network = self

    def add_source_global(self, source):

        source.network = self

        for agent in self.agents:
            source.connect_to(agent)

    def add_source_local(self, source, agent):

        source.network = self

        uid = source.uuid
        source = Node.query\
            .filter_by(uuid=uid).one()

        source.connect_to(agent)

    def add_agent(self, agent):
        agent.network = self
        return []

    def __len__(self):
        raise SyntaxError(
            "len is not defined for networks. " +
            "Use len(net.agents) or len(net.sources) instead.")

    def __repr__(self):
        return "<Network-{}-{} with {} agents, {} sources, {} vectors>".format(
            self.uuid[:6],
            self.type,
            len(self.agents),
            len(self.sources),
            len(self.vectors))

    def print_verbose(self):
        print "Agents: "
        for a in self.agents:
            print a

        print "\nSources: "
        for s in self.sources:
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

    # the destination of the info
    destination_uuid = Column(
        String(32), ForeignKey('node.uuid'), nullable=False)
    destination = relationship(Node, foreign_keys=[destination_uuid])

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
