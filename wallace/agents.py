#from sqlalchemy import desc
from .models import Info, Agent
from .information import Gene, Meme


class ReplicatorAgent(Agent):
    """
    The ReplicatorAgent is a simple extension of the base Agent.
    It has two differences: 1 - it has an update function that copies
    any incoming transmissions. 2 - by default it sends all its infos
    when transmitting.
    """
    __mapper_args__ = {"polymorphic_identity": "replicator_agent"}

    def update(self, infos):
        """Replicate the incoming information."""
        for info_in in infos:
            self.replicate(info_in)

    def _what(self):
        return self.infos()
