import numpy as np


class MoranProcess(object):
    """The generalized Moran process plays out over a network. At each time
    step, an individual is chosen for death and an individual is chosen for
    reproduction. The individual that reproduces replaces the one that dies.
    So far, the process is neutral and there is no mutation.
    """

    def __init__(self, network, steps):
        self.network = network
        self.steps = steps

    def run(self, verbose=True):
        idx_replacements = np.random.randint(0, len(self.network), (2, self.steps))

        for i in xrange(self.steps):
            replacer = self.network.agents[idx_replacements[0, i]]
            replaced = self.network.agents[idx_replacements[1, i]]

            if verbose:
                print "{}: {} replaces {}: {}".format(
                    replacer, replacer.genome, replaced, replaced.genome)

            replaced.update(replacer)
