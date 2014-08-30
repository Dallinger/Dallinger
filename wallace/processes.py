import numpy as np
import models
from sqlalchemy import desc


class RandomWalkFromSource(object):
    """Takes a random walk over a network, starting at a node randomly selected
    from those that receive input from a source."""

    def __init__(self, network):
        self.db = network.db
        self.network = network

    def get_latest_vector(self):
        return self.db.query(models.Transmission).order_by(
            desc(models.Transmission.transmit_time)).first()

    def step(self, verbose=True):

        # sourced_agents = [vector.destination for source in self.network.sources
        #                   for vector in source.outgoing_vectors]

        # replacer = np.random.choice(sourced_agents)

        replacer = self.get_latest_vector().destination

        options = replacer.outgoing_vectors

        if options:
            replaced = options[np.random.randint(0, len(options))].destination
            replacer.transmit(replaced)

            if verbose:
                print "{}: {} replaces {}: {}".format(
                    replacer, replacer.genome, replaced, replaced.genome)

            replacer = replaced
            self.db.commit()

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

    def step(self, verbose=True):
        n = len(self.network)
        replacer = self.network.agents[np.random.randint(0, n)]
        options = replacer.outgoing_vectors
        replaced = options[np.random.randint(0, len(options))].destination

        if verbose:
            print "{}: {} replaces {}: {}".format(
                replacer, replacer.genome, replaced, replaced.genome)

        replacer.transmit(replaced)
        self.db.commit()
