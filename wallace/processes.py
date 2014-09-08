import numpy as np
import models
from sqlalchemy import desc


class RandomWalkFromSource(object):
    """Takes a random walk over a network, starting at a node randomly selected
    from those that receive input from a source."""

    def __init__(self, network):
        self.db = network.db
        self.network = network

    def get_latest_transmission(self):
        return self.db.query(models.Transmission).order_by(
            desc(models.Transmission.transmit_time)).first()

    def step(self, verbose=True):

        latest_transmission = self.get_latest_transmission()

        if latest_transmission is None:  # first step, replacer is a source
            replacer = np.random.choice(self.network.sources)
        else:
            replacer = self.get_latest_transmission().destination

        options = replacer.outgoing_vectors

        if options:
            replaced = np.random.choice(options).destination
            replacer.transmit(replaced)
            self.db.commit()

            # FIXME: Testing placeholder
            replaced.receive_all()

        else:
            raise RuntimeError("No outgoing connections to choose from.")


class MoranProcess(object):
    """The generalized Moran process plays out over a network. At each time
    step, an individual is chosen for death and an individual is chosen for
    reproduction. The individual that reproduces replaces the one that dies.
    So far, the process is neutral and there is no mutation.
    """

    def __init__(self, network):
        self.db = network.db
        self.network = network

    def get_latest_transmission(self):
        return self.db.query(models.Transmission).order_by(
            desc(models.Transmission.transmit_time)).first()

    def step(self, verbose=True):

        if len(self.network) > 1:

            latest_transmission = self.get_latest_transmission()

            if latest_transmission is None:  # first step, replacer is a source
                replacer = np.random.choice(self.network.sources)
            else:
                replacer = np.random.choice(self.network.agents)

            replaced = np.random.choice(replacer.outgoing_vectors).destination
            replacer.transmit(replaced)
            self.db.commit()

            # FIXME: Testing placeholder
            replaced.receive_all()
