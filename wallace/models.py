from uuid import uuid4
from datetime import datetime

# get the connection to the database
from .db import Base

# various sqlalchemy imports
from sqlalchemy import ForeignKey, desc
from sqlalchemy import Column, String, Text, Enum
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func, select
from sqlalchemy.ext.associationproxy import association_proxy

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def new_uuid():
    return uuid4().hex


def timenow():
    time = datetime.now()
    return time.strftime(DATETIME_FMT)


class Environment(Base):
    __tablename__ = "environment"

    # the unique environment id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the environment type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    def state(self):
        state = Info\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Info.creation_time))\
            .first()
        return state

    # the time when the environment was created
    creation_time = Column(String(26), nullable=False, default=timenow)

    def __repr__(self):
        return "Environment-{}-{}".format(self.uuid[:6], self.type)


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

    def kill(self):
        self.status = "dead"
        self.time_of_death = timenow()

    def fail(self):
        self.status = "failed"
        self.time_of_death = timenow()

    # the information created by this node
    information = relationship(
        "Info", backref='origin', order_by="Info.creation_time")

    # the predecessors and successors
    successors = relationship(
        "Node",
        secondary="vector",
        primaryjoin="Node.uuid==vector.c.origin_uuid",
        secondaryjoin="Node.uuid==vector.c.destination_uuid",
        backref="predecessors"
    )

    def __repr__(self):
        return "Node-{}-{}".format(self.uuid[:6], self.type)

    def connect_to(self, other_node):
        """Creates a directed edge from self to other_node"""
        vector = Vector(origin=self, destination=other_node)
        self.outgoing_vectors.append(vector)

    def connect_from(self, other_node):
        """Creates a directed edge from other_node to self"""
        vector = Vector(origin=other_node, destination=self)
        self.incoming_vectors.append(vector)

    def transmit(self, what=None, who=None):
        """Transmits what to who"""
        """Will work provided what is an Info or a class of Info, or a list containing the two"""
        """If what=None the _what() method is called to generate what"""
        """Will work provided who is a Node you are connected to or a class of Nodes, or a list containing the two"""
        """If who=None the _who() method is called to generate who"""
        if what is None:
            what = self._what()
            if what is None or (isinstance(what, List) and None in what):
                raise ValueError("Your _what() method cannot return None.")
            else:
                self.transmit(what=what, who=who)
        elif isinstance(what, List):
            for which in what:
                self.transmit(what=which, who=who)
        elif issubclass(what, Info):
            infos = what\
                .query\
                .filter_by(origin_uuid=self.uuid)\
                .order_by(desc(Info.creation_time))\
                .all()
            self.transmit(what=infos, who=who)
        elif isinstance(what, Info):
            if who is None:
                who = self._who()
                if who is None or (isinstance(who,List) and None in who):
                    raise ValueError("Your _who() method cannot return None.")
                else:
                    self.transmit(what=what, who=who)
            elif isinstance(who, List):
                for whom in who:
                    self.transmit(what=what, who=whom)
            elif issubclass(who, Node):
                whom = successors\
                .query\
                .all()
                whom = [w for w in whom if isinstance(w,who)]
            elif isinstance(who, Node):
                if not self.has_connection_to(who):
                    raise ValueError(
                        "You are trying to transmit from'{}' to '{}', but they are not connected".format(self, who))
                else:
                    t = Transmission(info=what, destination=who)
                    what.transmissions.append(t)
            else:
                raise ValueError("You are trying to transmit to '{}', but it is not a Node").format(who)
        else
            raise ValueError("You are trying to transmit '{}', but it is not an Info").format(what)

    def _what(self):
        raise NotImplementedError("You need to override the default _what method if you want to transmit(what=None)")

    def _who(self):
        raise NotImplementedError("You need to override the default _who method if you want to transmit(who=None)")

    def update(self, infos):
        raise NotImplementedError(
            "The update method of node '{}' has not been overridden".format(self))

    @hybrid_property
    def outdegree(self):
        """The outdegree (number of outgoing edges) of this node."""
        return len(self.outgoing_vectors)

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
        return other_node in self.successors

    def has_connection_from(self, other_node):
        """Whether this node has a connection from 'other_node'."""
        return other_node in self.predecessors

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

    def __repr__(self):
        return "Info-{}-{}".format(self.uuid[:6], self.type)

    def copy_to(self, other_node):
        cls = type(self)
        return cls(origin=other_node, contents=self.contents)


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

    def apply(self, info_in):
        return NotImplementedError

    def __repr__(self):
        return "Transformation-{}".format(self.uuid[:6])
