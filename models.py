import datetime

# various sqlalchemy imports
from sqlalchemy import Integer, ForeignKey, ForeignKeyConstraint
from sqlalchemy import Column, Enum, String, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, scoped_session
from sqlalchemy import create_engine

# create the connection to the database
engine = create_engine("mysql://root@localhost/wallace")
db = scoped_session(sessionmaker(
    autocommit=False, autoflush=False, bind=engine))

Base = declarative_base()
Base.query = db.query_property()


class Node(Base):
    __tablename__ = "node"

    # the unique node id
    id = Column(Integer, primary_key=True)

    # the node type -- it MUST be one of these
    type = Column(Enum("source", "participant", "filter"), nullable=False)

    # a human-readable name for the node
    name = Column(String(128))

    def __init__(self, name, type):
        self.name = name
        self.type = type

    def __repr__(self):
        return "Node-{}-{}".format(self.id, self.type)


class Vector(Base):
    __tablename__ = "vector"

    # the origin node
    origin_id = Column(Integer, ForeignKey('node.id'), primary_key=True)
    origin = relationship(Node, foreign_keys=[origin_id])

    # the destination node
    destination_id = Column(Integer, ForeignKey('node.id'), primary_key=True)
    destination = relationship(Node, foreign_keys=[destination_id])

    # all transmissions that have occurred along this vector
    transmissions = relationship("Transmission", backref='vector')

    def __init__(self, origin, destination):
        self.origin = origin
        self.destination = destination

    def __repr__(self):
        return "Vector-{}-{}".format(self.origin_id, self.destination_id)


class Meme(Base):
    __tablename__ = "meme"

    # the unique meme id
    id = Column(Integer, primary_key=True)

    # the node that produced this meme
    origin_id = Column(Integer, ForeignKey('node.id'), nullable=False)
    origin = relationship("Node", backref="outgoing_memes")

    # the time when the meme was created
    creation_time = Column(DateTime, nullable=False)

    # the contents of the meme
    contents = Column(Text(4294967295))

    def __init__(self, origin, contents=None):
        self.creation_time = datetime.datetime.now()
        self.origin = origin
        self.contents = contents

    def __repr__(self):
        return "Meme-{}".format(self.id)

    def transmit(self, destination):
        """Transmit the meme to the given destination."""
        Transmission(self, destination)


class Transmission(Base):
    __tablename__ = "transmission"

    # the unique transmission id
    id = Column(Integer, primary_key=True)

    # the meme that was transmitted
    meme_id = Column(Integer, ForeignKey('meme.id'), nullable=False)
    meme = relationship(Meme, backref='transmissions')

    # the origin and destination nodes, which gives us a reference to
    # the vector that this transmission occurred along
    origin_id = Column(Integer, nullable=False)
    destination_id = Column(Integer, nullable=False)
    __table_args__ = (
        ForeignKeyConstraint(
            ["origin_id", "destination_id"],
            ["vector.origin_id", "vector.destination_id"]),
        {})

    # the time at which the transmission occurred
    transmit_time = Column(DateTime, nullable=False)

    def __init__(self, meme, destination):
        self.transmit_time = datetime.datetime.now()
        self.meme = meme
        self.origin_id = meme.origin_id
        self.destination_id = destination.id

    def __repr__(self):
        return "Transmission-{}".format(self.id)


###########################################################################

if __name__ == "__main__":
    import numpy as np

    # initialize the database
    Base.metadata.create_all(bind=engine)

    # create the source node (which generates the stimuli)
    source = Node("Stimuli", "source")
    db.add(source)

    # create participants
    for name in ["Jess", "Jordan", "Tom", "Mike", "Stephan"]:
        p = Node(name, "participant")
        db.add(p)
    db.commit()

    # create vectors between participants
    participants = db.query(Node).filter_by(type="participant").all()
    for p1 in participants:
        vector = Vector(source, p1)
        db.add(vector)
        for p2 in participants:
            if p1.id != p2.id:
                vector = Vector(p1, p2)
                db.add(vector)
    db.commit()

    # create the initial stimulus
    stim = Meme(source, contents="0-0-0-0-0")
    db.add(stim)
    db.commit()

    for i in xrange(100):
        # first pick the vector, and send the stimulus
        vectors = db.query(Vector).filter_by(origin_id=stim.origin_id).all()
        vidx = np.random.randint(0, len(vectors))
        p = vectors[vidx].destination
        stim.transmit(p)

        # then mutate the stimulus and add the new meme to the database
        contents = [int(x) for x in stim.contents.split("-")]
        idx = np.random.randint(0, len(contents))
        contents[idx] += 1
        contents = "-".join([str(x) for x in contents])
        stim = Meme(p, contents)
        db.add(stim)
        db.commit()
