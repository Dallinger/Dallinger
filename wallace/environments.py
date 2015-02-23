from sqlalchemy import ForeignKey, Column, String, desc
from .models import Node, Info
from information import State


class Environment(Node):

    """Defines an environment node.

    Environments are nodes that have a state and that receive a transmission
    from anyone that observes them.
    """

    __tablename__ = "environment"
    __mapper_args__ = {"polymorphic_identity": "environment"}

    # the unique environment id
    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    @property
    def state(self):
        """The state is the most recently created info of type State."""
        return State\
            .query\
            .filter_by(origin_uuid=self.uuid)\
            .order_by(desc(Info.creation_time))\
            .first()

    def get_observed(self, by_whom=None):
        """When observed, transmit the state."""
        self.transmit(what=self.state, to_whom=by_whom)

    def __repr__(self):
        """Print the environment in a nice format."""
        return "Environment-{}-{}".format(self.uuid[:6], self.type)
