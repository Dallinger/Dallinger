from . import models
from .db import init_db


class Wallace(object):

    def __init__(self, drop_all=False):
        """Initialize Wallace."""
        self.db = init_db(drop_all=drop_all)

    def add_node(self, name, type):
        """Add a new node. The 'type' should be either "participant",
        "source", or "filter".

        """
        # check that the node type is valid
        if type not in models.NODE_TYPES:
            raise ValueError("invalid type: {}".format(type))

        node = models.Node(name, type)
        self.db.add(node)
        self.db.commit()
        return node

    def get_nodes(self):
        """Get all nodes in the database."""
        return self.db.query(models.Node).all()

    def add_participant(self, name):
        """Add a new participant node."""
        return self.add_node(name, "participant")

    def get_participants(self):
        """Get all participants in the database."""
        return self.db.query(models.Node).filter_by(type="participant").all()

    def add_source(self, name):
        """Add a new source node."""
        return self.add_node(name, "source")

    def get_sources(self):
        """Get all source nodes in the database."""
        return self.db.query(models.Node).filter_by(type="source").all()

    def add_filter(self, name):
        """Add a new filter node."""
        return self.add_node(name, "filter")

    def get_filters(self):
        """Get all filter nodes in the database."""
        return self.db.query(models.Node).filter_by(type="filter").all()

    def add_vector(self, origin, destination):
        """Add a new vector from 'origin' to 'destination'."""
        vector = models.Vector(origin, destination)
        self.db.add(vector)
        self.db.commit()
        return vector

    def get_vectors(self, origin=None, destination=None):
        """Get the list of vectors in the database, optionally filtered by
        their origin and/or destination.

        """
        if origin and destination:
            return self.db.query(models.Vector).filter_by(
                origin_id=origin.id, destination_id=destination.id).all()
        elif origin:
            return self.db.query(models.Vector).filter_by(
                origin_id=origin.id).all()
        elif destination:
            return self.db.query(models.Vector).filter_by(
                destination_id=destination.id).all()
        else:
            return self.db.query(models.Vector).all()

    def add_meme(self, origin, contents=None):
        """Add a new meme, created by 'origin'."""
        meme = models.Meme(origin, contents=contents)
        self.db.add(meme)
        self.db.commit()
        return meme

    def get_memes(self):
        """Get all memes in the database."""
        return self.db.query(models.Meme).all()

    def get_transmissions(self):
        """Get all transmissions in the database."""
        return self.db.query(models.Transmission).all()
