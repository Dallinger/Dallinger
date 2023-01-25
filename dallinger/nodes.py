"""Define kinds of nodes: agents, sources, and environments."""

import random
from operator import attrgetter

from sqlalchemy import Float
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import cast

from dallinger.information import State
from dallinger.models import Info, Node


class Agent(Node):
    """A Node with fitness."""

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
        return cast(self.property1, Float)


class ReplicatorAgent(Agent):
    """An agent that copies incoming transmissions."""

    __mapper_args__ = {"polymorphic_identity": "replicator_agent"}

    def update(self, infos):
        """Replicate the incoming information."""
        for info_in in infos:
            self.replicate(info_in=info_in)


class Source(Node):
    """An AI Node that only sends transmissions.

    By default, when asked to transmit, a Source creates and sends
    a new Info. Sources cannot receive transmissions.
    """

    __mapper_args__ = {"polymorphic_identity": "generic_source"}

    def _what(self):
        """What to transmit by default."""
        return self.create_information()

    def create_information(self):
        """Create new infos on demand."""
        info = self._info_type()(origin=self, contents=self._contents())
        return info

    def _info_type(self):
        """The type of info to be created."""
        return Info

    def _contents(self):
        """The contents of new infos."""
        raise NotImplementedError(
            "{}.contents() needs to be defined.".format(type(self))
        )

    def receive(self, what):
        """Raise an error if asked to receive a transmission."""
        raise Exception("Sources cannot receive transmissions.")


class RandomBinaryStringSource(Source):
    """A source that transmits random binary strings."""

    __mapper_args__ = {"polymorphic_identity": "random_binary_string_source"}

    def _contents(self):
        """Generate a random binary string."""
        return "".join([str(random.randint(0, 1)) for i in range(2)])


class Environment(Node):
    """A node with a state."""

    __mapper_args__ = {"polymorphic_identity": "environment"}

    def state(self, time=None):
        """The most recently-created info of type State at the specfied time.

        If time is None then it returns the most recent state as of now.
        """
        if not len(self.infos(type=State)):
            return None

        if time is None:
            return max(self.infos(type=State), key=attrgetter("creation_time"))
        else:
            states = [s for s in self.infos(type=State) if s.creation_time < time]
            return max(states, key=attrgetter("creation_time"))

    def update(self, contents, **kwargs):
        state = State(origin=self, contents=contents, **kwargs)
        return state

    def _what(self):
        """Return the most recent state."""
        return self.state()
