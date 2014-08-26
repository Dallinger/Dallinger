from uuid import uuid4
from datetime import datetime

# get the connection to the database
from .db import Base

# various sqlalchemy imports
from sqlalchemy import ForeignKey, ForeignKeyConstraint
from sqlalchemy import Column, String, DateTime, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property


def new_id():
    return uuid4().hex


class Node(Base):
    __tablename__ = "node"

    # the unique node id
    id = Column(String(32), primary_key=True, default=new_id)

    # the node type -- this allows for inheritance
    type = Column(String(50))
    __mapper_args__ = {
        'polymorphic_on': type,
        'polymorphic_identity': 'base'
    }

    # incoming and outgoing transmissions to this node
    incoming_transmissions = relationship(
        "Transmission",
        primaryjoin="foreign(Transmission.destination_id) == Node.id",
        order_by="Transmission.transmit_time")
    outgoing_transmissions = relationship(
        "Transmission",
        primaryjoin="foreign(Transmission.origin_id) == Node.id",
        order_by="Transmission.transmit_time")

    def __repr__(self):
        return "Node-{}-{}".format(self.id[:6], self.type)

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
            meme=meme, origin_id=self.id, destination_id=other_node.id)

    def broadcast(self, meme):
        """Broadcast the specified meme to all connected nodes. The meme must
        have been created by this node.

        """
        for vector in self.outgoing_vectors:
            self.transmit(meme, vector.destination)

    @hybrid_property
    def outdegree(self):
        """The outdegree (number of outgoing edges) of this node."""
        return len(self.outgoing_vectors)

    @hybrid_property
    def indegree(self):
        """The indegree (number of incoming edges) of this node."""
        return len(self.incoming_vectors)

    def has_connection_to(self, other_node):
        """Whether this node has a connection to 'other_node'."""
        for vector in self.outgoing_vectors:
            if vector.destination_id == other_node.id:
                return True
        return False

    def has_connection_from(self, other_node):
        """Whether this node has a connection from 'other_node'."""
        for vector in self.incoming_vectors:
            if vector.origin_id == other_node.id:
                return True
        return False


class Vector(Base):
    __tablename__ = "vector"

    # the origin node
    origin_id = Column(String(32), ForeignKey('node.id'), primary_key=True)
    origin = relationship(
        Node, foreign_keys=[origin_id],
        backref="outgoing_vectors")

    # the destination node
    destination_id = Column(
        String(32), ForeignKey('node.id'), primary_key=True)
    destination = relationship(
        Node, foreign_keys=[destination_id],
        backref="incoming_vectors")

    def __repr__(self):
        return "Vector-{}-{}".format(
            self.origin_id[:6], self.destination_id[:6])


class Meme(Base):
    __tablename__ = "meme"

    # the unique meme id
    id = Column(String(32), primary_key=True, default=new_id)

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
        return "Meme-{}-{}".format(self.id[:6], self.type)


class Transmission(Base):
    __tablename__ = "transmission"

    # the unique transmission id
    id = Column(String(32), primary_key=True, default=new_id)

    # the meme that was transmitted
    meme_id = Column(String(32), ForeignKey('meme.id'), nullable=False)
    meme = relationship(Meme, backref='transmissions')

    # the origin and destination nodes, which gives us a reference to
    # the vector that this transmission occurred along
    origin_id = Column(String(32), nullable=False)
    destination_id = Column(String(32), nullable=False)
    vector = relationship(Vector, backref='transmissions')

    # these are special constraints that ensure (1) that the meme
    # origin is the same as the vector origin and (2) that the vector
    # is defined by the origin id and the destination id
    __table_args__ = (
        ForeignKeyConstraint(
            ["origin_id", "destination_id"],
            ["vector.origin_id", "vector.destination_id"]),
        {})

    # the time at which the transmission occurred
    transmit_time = Column(DateTime, nullable=False, default=datetime.now)

    def __repr__(self):
        return "Transmission-{}".format(self.id[:6])
