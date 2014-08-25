from uuid import uuid4
from datetime import datetime

# get the connection to the database
from .db import Base

# various sqlalchemy imports
from sqlalchemy import ForeignKey, ForeignKeyConstraint
from sqlalchemy import Column, Enum, String, DateTime, Text
from sqlalchemy.orm import relationship

# the types that nodes can be
NODE_TYPES = ("source", "agent", "filter")


def new_id():
    return uuid4().hex


class Node(Base):
    __tablename__ = "node"

    # the unique node id
    id = Column(String(32), primary_key=True, default=new_id)

    # the node type -- it MUST be one of these
    type = Column(Enum(*NODE_TYPES), nullable=False)

    def __repr__(self):
        return "Node-{}-{}".format(self.id[:6], self.type)

    def connect_to(self, other_node):
        """Creates a directed edge from self to other_node"""
        return Vector(origin=self, destination=other_node)

    def connect_from(self, other_node):
        """Creates a directed edge from other_node to self"""
        return Vector(origin=other_node, destination=self)


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

    # the node that produced this meme
    origin_id = Column(String(32), ForeignKey('node.id'), nullable=False)
    origin = relationship("Node", backref="outgoing_memes")

    # the time when the meme was created
    creation_time = Column(DateTime, nullable=False, default=datetime.now)

    # the contents of the meme
    contents = Column(Text(4294967295))

    def __repr__(self):
        return "Meme-{}".format(self.id[:6])


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
