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
        try:
            return float(self.property1)
        except TypeError:
            return None

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

    """A Source is a Node that sends transmissions.

    By default, when asked to transmit, a Source creates and sends
    a new Info. Sources cannot receive transmissions.
    """

    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    def _what(self):
        """ Determines what to transmit by default. """
        return self.create_information()

    def create_information(self):
        """ Called by _what(), creates new infos on demand. """
        info = Info(
            origin=self,
            contents=self._contents())
        return info

    def _contents(self):
        """ Determines the contents of new infos created on demand. """
        raise NotImplementedError(
            "{}.contents() needs to be defined.".format(type(self)))

    def receive(self, what):
        """ Sources cannot receive transmissions."""
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
