from uuid import uuid4
from datetime import datetime

# get the connection to the database
from .db import Base

# various sqlalchemy imports
from sqlalchemy import ForeignKey
from sqlalchemy import Column, String, Text
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

    def transmit(self, info, other_node):
        """Transmits the specified info to 'other_node'. The info must have
        been created by this node, and this node must be connected to
        'other_node'.

        """
        if not self.has_connection_to(other_node):
            raise ValueError(
                "'{}' is not connected to '{}'".format(self, other_node))
        if not info.origin_uuid == self.uuid:
            raise ValueError(
                "'{}' was not created by '{}'".format(info, self))

        t = Transmission(info=info, destination=other_node)
        info.transmissions.append(t)
        other_node.update(info)

    def broadcast(self, info):
        """Broadcast the specified info to all connected nodes. The info must
        have been created by this node.

        """
        for vector in self.outgoing_vectors:
            self.transmit(info, vector.destination)

    def update(self, info):
        pass

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


class Vector(Base):
    __tablename__ = "vector"

    # the origin node
    origin_uuid = Column(String(32), ForeignKey('node.uuid'), primary_key=True)
    origin = relationship(
        Node, foreign_keys=[origin_uuid],
        backref="outgoing_vectors")

    # the destination node
    destination_uuid = Column(
        String(32), ForeignKey('node.uuid'), primary_key=True)
    destination = relationship(
        Node, foreign_keys=[destination_uuid],
        backref="incoming_vectors")

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
    contents = Column(Text(4294967295))

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

    def __repr__(self):
        return "Transmission-{}".format(self.uuid[:6])
