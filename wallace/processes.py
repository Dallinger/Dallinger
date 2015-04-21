import models
from models import Agent, Source
from sqlalchemy import desc
import random


class Process(object):

    def __init__(self, network):
        self.network = network

    def step(self, verbose=True):
        raise(NotImplementedError("Your process needs to override the step() function"))

    def is_begun(self):
        """To tell if the process has started yet, check if there have been any
        transmissions."""
        return len(models.Transmission.query.all()) > 0

    def get_latest_transmission_recipient(self):
        all_transmissions = models.Transmission\
            .query\
            .order_by(desc(models.Transmission.transmit_time))\
            .all()

        return next(
            (t.destination for t in all_transmissions
                if (t.destination.status != "failed") and
                (t.destination.network == self.network)),
            None)


class RandomWalkFromSource(Process):
    """Takes a random walk over a network, starting at a node randomly selected
    from those that receive input from a source."""

    def __init__(self, network):
        self.network = network

    def step(self, verbose=True):

        latest_recipient = self.get_latest_transmission_recipient()

        if (not self.is_begun()) or (latest_recipient is None):
            replacer = random.choice(self.network.nodes(type=Source))
        else:
            replacer = latest_recipient

        options = [v for v in replacer.outgoing_vectors()
                   if v.destination.status == "alive"]

        if options:
            replaced = random.choice(options).destination
            replacer.transmit(to_whom=replaced)
        else:
            raise RuntimeError("No outgoing connections to choose from.")


class MoranProcessCultural(Process):
    """The generalized cultural Moran process plays out over a network. At each
    time step, an individual is chosen to receive information from another
    individual. Nobody dies, but perhaps their ideas do."""

    def __init__(self, network):
        self.network = network

    def step(self, verbose=True):

        if not self.is_begun():  # first step, replacer is a source
            replacer = random.choice(self.network.nodes(type=Source))
            replacer.transmit()
        else:
            replacer = random.choice(self.network.nodes(type=Agent))
            replaced = random.choice(replacer.downstream_nodes(type=Agent))
            replacer.transmit(what=replacer.infos()[-1], to_whom=replaced)


class MoranProcessSexual(Process):
    """The generalized sexual Moran process also plays out over a network. At
    each time step, and individual is chosen for replication and another
    individual is chosen to die. The replication replaces the one who dies.

    For this process to work you need to add a new agent before calling step.
    """

    def __init__(self, network):
        self.network = network

    def step(self, verbose=True):

        if not self.is_begun():
            replacer = random.choice(self.network.nodes(type=Source))
            replacer.transmit()
        else:
            replacer = random.choice(self.network.nodes(type=Agent)[:-1])
            replaced = random.choice(replacer.downstream_nodes(type=Agent))

            # Find the baby just added
            baby = self.network.nodes(type=Agent)[-1]

            # Give the baby the same outgoing connections as the replaced.
            for node in replaced.downstream_nodes():
                baby.connect_to(node)

            # Give the baby the same incoming connections as the replaced.
            for node in replaced.upstream_nodes():
                node.connect_to(baby)

            # Kill the replaced agent.
            replaced.kill()

            # Endow the baby with the ome of the replacer.
            replacer.transmit(to_whom=baby)
