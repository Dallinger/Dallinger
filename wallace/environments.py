from sqlalchemy import ForeignKey, Column, String, desc
from .models import Node
from information import State


class Environment(Node):

    """
    Environments are Nodes with the following features:
    1 - they have the get_observed function
    2 - by default they transmit the most recent info of type State
    3 - the state() method can be passed a time to get the state at that time
    """

    __tablename__ = "environment"
    __mapper_args__ = {"polymorphic_identity": "environment"}

    # the unique environment id
    uuid = Column(String(32), ForeignKey("node.uuid"), primary_key=True)

    def state(self, time=None):
        """The most recently created info of type State. If you specify a time,
        it will return the most recent state at that point in time."""
        if time is None:
            return self.infos(type=State)[-1]
        else:
            return State\
                .query\
                .filter_by(origin_uuid=self.uuid)\
                .filter(State.creation_time < time)\
                .order_by(desc(State.creation_time))\
                .first()

    def _what(self):
        return self.state()

    def __repr__(self):
        """Print the environment in a nice format."""
        return "Environment-{}-{}".format(self.uuid[:6], self.type)
