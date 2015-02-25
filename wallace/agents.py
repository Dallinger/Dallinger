from sqlalchemy import desc
from .models import Info, Agent
from .information import Gene, Meme


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
