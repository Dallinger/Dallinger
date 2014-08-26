import numpy as np


class MoranProcess(object):
    """The generalized Moran process plays out over a network. At each time
    step, an individual is chosen for death and an individual is chosen for
    reproduction. The individual that reproduces replaces the one that dies.
    So far, the process is neutral and there is no mutation.
    """

    def __init__(self, network, steps):
        self.db = network.db
        self.network = network
        self.steps = steps

    def run(self, verbose=True):
        n = len(self.network)

        for i in xrange(self.steps):
            replacer = self.network.agents[np.random.randint(0, n)]
            options = replacer.outgoing_vectors
            replaced = options[np.random.randint(0, len(options))].destination

            if verbose:
                print "{}: {} replaces {}: {}".format(
                    replacer, replacer.genome, replaced, replaced.genome)

            replacer.transmit(replaced)
            self.db.commit()
