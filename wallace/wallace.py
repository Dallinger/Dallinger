from . import models
from .db import Base, engine, db


class Wallace(object):

    def __init__(self, drop_all=False):
        # initialize the database
        if drop_all:
            Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)

    def add_node(self, name, type):
        node = models.Node(name, type)
        db.add(node)
        db.commit()
        return node

    @property
    def nodes(self):
        return db.query(models.Node).all()

    def add_participant(self, name):
        return self.add_node(name, "participant")

    @property
    def participants(self):
        return db.query(models.Node).filter_by(type="participant").all()

    def add_source(self, name):
        return self.add_node(name, "source")

    @property
    def sources(self):
        return db.query(models.Node).filter_by(type="source").all()

    def add_filter(self, name):
        return self.add_node(name, "filter")

    @property
    def filters(self):
        return db.query(models.Node).filter_by(type="filter").all()

    def add_vector(self, origin, destination):
        vector = models.Vector(origin, destination)
        db.add(vector)
        db.commit()
        return vector

    @property
    def vectors(self):
        return db.query(models.Vector).all()

    def get_vectors(self, origin=None, destination=None):
        if origin and destination:
            return db.query(models.Vector).filter_by(
                origin_id=origin.id, destination_id=destination.id).all()
        elif origin:
            return db.query(models.Vector).filter_by(
                origin_id=origin.id).all()
        elif destination:
            return db.query(models.Vector).filter_by(
                destination_id=destination.id).all()
        else:
            return db.query(models.Vector).all()

    def add_meme(self, origin, contents=None):
        meme = models.Meme(origin, contents=contents)
        db.add(meme)
        db.commit()
        return meme

    @property
    def memes(self):
        return db.query(models.Meme).all()

    @property
    def transmissions(self):
        return db.query(models.Transmission).all()
