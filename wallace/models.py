from uuid import uuid4
from datetime import datetime

# get the connection to the database
from .db import Base

# various sqlalchemy imports
from sqlalchemy import ForeignKey, ForeignKeyConstraint
from sqlalchemy import Column, Enum, String, DateTime, Text
from sqlalchemy.orm import relationship

# the types that nodes can be
NODE_TYPES = ("source", "participant", "filter")


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


class Vector(Base):
    __tablename__ = "vector"

    # the origin node
    origin_id = Column(String(32), ForeignKey('node.id'), primary_key=True)
    origin = relationship(
        Node, foreign_keys=[origin_id], backref="outgoing_vectors")

    # the destination node
    destination_id = Column(
        String(32), ForeignKey('node.id'), primary_key=True)
    destination = relationship(
        Node, foreign_keys=[destination_id], backref="incoming_vectors")

    # all transmissions that have occurred along this vector
    transmissions = relationship("Transmission", backref='vector')

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

    # this is a special constraint that says that the origin_id and
    # destination_id *together* make up the unique id for the vector
    __table_args__ = (
        ForeignKeyConstraint(
            ["origin_id", "destination_id"],
            ["vector.origin_id", "vector.destination_id"]),
        {})

    # the time at which the transmission occurred
    transmit_time = Column(DateTime, nullable=False, default=datetime.now)

    def __init__(self, meme, destination):
        self.meme = meme
        self.origin_id = meme.origin_id
        self.destination_id = destination.id

    def __repr__(self):
        return "Transmission-{}".format(self.id[:6])
