from sqlalchemy import ForeignKey, Column, String, desc
from datetime import datetime

from .models import Node, Info, Transmission
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

    def update(self, info):
        raise NotImplementedError

    def broadcast(self):
        for vector in self.outgoing_vectors:
            self.transmit(vector.destination)

    def receive_all(self):
        pending_transmissions = self.pending_transmissions
        for transmission in pending_transmissions:
            transmission.receive_time = timenow()
            transmission.mark_received()
            self.update(transmission.info)


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

    def update(self, info):
        info.copy_to(self)


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

    def update(self, info):
        info.copy_to(self)

    def _selector(self):
        return [self.info]
