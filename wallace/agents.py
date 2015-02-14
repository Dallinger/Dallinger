from sqlalchemy import ForeignKey, Column, String, desc
from datetime import datetime

from .models import Node, Info, Transmission, Transformation
from .transformations import Replication
from .information import Gene, Meme

DATETIME_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def timenow():
    time = datetime.now()
    return time.strftime(DATETIME_FMT)


class Agent(Node):
    """Agents have genomes and memomes, and update their contents when faced.
    By default, agents transmit unadulterated copies of their genomes and
    memomes, with no error or mutation.
    """

    __tablename__ = "agent"
    __mapper_args__ = {"polymorphic_identity": "agent"}

    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    def _selector(self):
        raise NotImplementedError

    def update(self, infos):
        raise NotImplementedError

    def replicate(self, info_in):
        """Create a new info of the same type as the incoming info."""
        info_type = type(info_in)
        info_out = info_type(origin=self, contents=info_in.contents)

        # Register the transformation.
        Replication(info_out=info_out, info_in=info_in, node=self)


    def receive_all(self):
        pending_transmissions = self.pending_transmissions
        for transmission in pending_transmissions:
            transmission.receive_time = timenow()
            transmission.mark_received()
        self.update([t.info for t in pending_transmissions])


class BiologicalAgent(Agent):

    __mapper_args__ = {"polymorphic_identity": "biological_agent"}

    @property
    def omes(self):
        return [self.genome, self.memome]

    @property
    def genome(self):
        genome = Gene\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Gene.creation_time))\
            .all()
        return genome

    @property
    def memome(self):
        memome = Meme\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Meme.creation_time))\
            .all()
        return memome

    def _selector(self):
        """Returns a list of Infos that should be transmitted by default, when
        a selector is not specified."""
        return [self.genome[0], self.memome[0]]

    def update(self, infos):
        for info_in in infos:
            self.replicate(info_in)


class ReplicatorAgent(Agent):

    __mapper_args__ = {"polymorphic_identity": "replicator_agent"}

    @property
    def info(self):
        info = Info\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Info.creation_time))\
            .first()
        return info

    def update(self, infos):
        """Replicate the incoming information."""
        for info_in in infos:
            self.replicate(info_in)

    def _what(self):
        return [self.info]
