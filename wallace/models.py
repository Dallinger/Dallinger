from uuid import uuid4
from datetime import datetime

# get the connection to the database
from .db import Base

# various sqlalchemy imports
from sqlalchemy import ForeignKey, ForeignKeyConstraint
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql import func, select


def new_uuid():
    return uuid4().hex


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
    creation_time = Column(DateTime, nullable=False, default=datetime.now)

    # incoming and outgoing transmissions to this node
    incoming_transmissions = relationship(
        "Transmission",
        primaryjoin="foreign(Transmission.destination_uuid) == Node.uuid",
        order_by="Transmission.transmit_time")
    outgoing_transmissions = relationship(
        "Transmission",
        primaryjoin="foreign(Transmission.origin_uuid) == Node.uuid",
        order_by="Transmission.transmit_time")

    def __repr__(self):
        return "Node-{}-{}".format(self.uuid[:6], self.type)

    def connect_to(self, other_node):
        """Creates a directed edge from self to other_node"""
        Vector(origin=self, destination=other_node)

    def connect_from(self, other_node):
        """Creates a directed edge from other_node to self"""
        Vector(origin=other_node, destination=self)

    def transmit(self, meme, other_node):
        """Transmits the specified meme to 'other_node'. The meme must have
        been created by this node, and this node must be connected to
        'other_node'.

        """
        if not self.has_connection_to(other_node):
            raise ValueError(
                "'{}' is not connected to '{}'".format(self, other_node))

        Transmission(
            meme=meme,
            origin_uuid=self.uuid,
            destination_uuid=other_node.uuid)

        other_node.update(meme)

    def broadcast(self, meme):
        """Broadcast the specified meme to all connected nodes. The meme must
        have been created by this node.

        """
        for vector in self.outgoing_vectors:
            self.transmit(meme, vector.destination)

    def update(self, meme):
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
        for vector in self.outgoing_vectors:
            if vector.destination_uuid == other_node.uuid:
                return True
        return False

    def has_connection_from(self, other_node):
        """Whether this node has a connection from 'other_node'."""
        for vector in self.incoming_vectors:
            if vector.origin_uuid == other_node.uuid:
                return True
        return False


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


class Meme(Base):
    __tablename__ = "meme"

    # the unique meme id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the meme type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # the time when the meme was created
    creation_time = Column(DateTime, nullable=False, default=datetime.now)

    # the contents of the meme
    contents = Column(Text(4294967295))

    def __repr__(self):
        return "Meme-{}-{}".format(self.uuid[:6], self.type)

    def duplicate(self):
        cls = type(self)
        return cls(contents=self.contents)


class Transmission(Base):
    __tablename__ = "transmission"

    # the unique transmission id
    uuid = Column(String(32), primary_key=True, default=new_uuid)

    # the meme that was transmitted
    meme_uuid = Column(String(32), ForeignKey('meme.uuid'), nullable=False)
    meme = relationship(Meme, backref='transmissions')

    # the origin and destination nodes, which gives us a reference to
    # the vector that this transmission occurred along
    origin_uuid = Column(String(32), nullable=False)
    destination_uuid = Column(String(32), nullable=False)
    vector = relationship(Vector, backref='transmissions')

    # these are special constraints that ensure (1) that the meme
    # origin is the same as the vector origin and (2) that the vector
    # is defined by the origin uuid and the destination uuid
    __table_args__ = (
        ForeignKeyConstraint(
            ["origin_uuid", "destination_uuid"],
            ["vector.origin_uuid", "vector.destination_uuid"]),
        {})

    # the time at which the transmission occurred
    transmit_time = Column(DateTime, nullable=False, default=datetime.now)

    def __repr__(self):
        return "Transmission-{}".format(self.uuid[:6])
