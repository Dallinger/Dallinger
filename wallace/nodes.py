from wallace.models import *
from wallace.transformations import *
from wallace.information import *


###################################
# The Agent class and subclasses
###################################


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
    """
    The ReplicatorAgent is a simple extension of the base Agent.
    The only difference is that its update function copies
    any incoming transmissions.
    """
    __mapper_args__ = {"polymorphic_identity": "replicator_agent"}

    def update(self, infos):
        """Replicate the incoming information."""
        for info_in in infos:
            self.replicate(info_in)


###################################
# The Source class and subclasses
###################################


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


###################################
# The Environment class and subclasses
###################################

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
