"""Define kinds of nodes: agents, sources, and environments."""

from wallace.models import Node, Info
from wallace.information import State
from sqlalchemy import Integer
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import cast
from operator import attrgetter
import random


class Agent(Node):

    """An Agent is a Node with a fitness."""

    __mapper_args__ = {"polymorphic_identity": "agent"}

    @hybrid_property
    def fitness(self):
        """Endow agents with a numerical fitness."""
        if self.property1 is None:
            return None
        else:
            return float(self.property1)

    @fitness.setter
    def fitness(self, fitness):
        """Assign fitness to property1."""
        self.property1 = repr(fitness)

    @fitness.expression
    def fitness(self):
        """Retrieve fitness via property1."""
        return cast(self.property1, Integer)


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
            contents=self._contents())
        return info

    def _what(self):
        return self.create_information()

    def _contents(self):
        raise NotImplementedError(
            "{}.contents() needs to be defined.".format(type(self)))

    def receive(self, what):
        """Throw an exception if a source tries to receive information."""
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
            return max(self.infos(type=State), key=attrgetter('creation_time'))
        else:
            states = [
                s for s in self.infos(type=State) if s.creation_time < time]
            return max(states, key=attrgetter('creation_time'))

    def _what(self):
        return self.state()
