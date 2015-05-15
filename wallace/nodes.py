"""Define kinds of nodes: agents, sources, and environments."""

from wallace.models import Node, Info
from wallace.information import State
import random
from sqlalchemy import and_


class Agent(Node):

    """An Agent is a Node with a fitness."""

    __mapper_args__ = {"polymorphic_identity": "agent"}

    def set_fitness(self, fitness):
        self.property1 = repr(fitness)

    @property
    def fitness(self):
        if self.property1 is None:
            return None
        else:
            return float(self.property1)


class ReplicatorAgent(Agent):

    """An agent that copies incoming transmissions."""

    __mapper_args__ = {"polymorphic_identity": "replicator_agent"}

    def update(self, infos):
        """Replicate the incoming information."""
        for info_in in infos:
            self.replicate(info_in=info_in)


class Source(Node):

    """A Source is a Node that generates information.

    Unlike a base Node it has a create_information method. By default, when
    asked to transmit, a Source creates new information and sends that
    information. Sources cannot receive transmissions.
    """

    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    def create_information(self):
        """Create a new info with contents defined by the source."""
        info = Info(
            origin=self,
            origin_uuid=self.uuid,
            contents=self._contents())
        return info

    def _what(self):
        return self.create_information()

    def _contents(self):
        raise NotImplementedError(
            "{}.contents() needs to be defined.".format(type(self)))

    def receive(self, what):
        raise Exception("Sources cannot receive transmissions.")


class RandomBinaryStringSource(Source):

    """A source that transmits random binary strings."""

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    def _contents(self):
        return "".join([str(random.randint(0, 1)) for i in range(2)])


class Environment(Node):

    """Environments are nodes with a state."""

    __mapper_args__ = {"polymorphic_identity": "environment"}

    def state(self, time=None):
        """The most recently-created info of type State.

        If given a timestamp, it will return the most recent state at that
        point in time.
        """
        if time is None:
            return self.infos(type=State)[-1]
        else:
            return State\
                .query\
                .filter(and_(
                    State.origin_uuid == self.uuid,
                    State.creation_time < time))\
                .first()

    def _what(self):
        return self.state()
