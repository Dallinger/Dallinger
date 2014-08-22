from uuid import uuid4
import numpy as np


class Agent(object):
    """Agents have genomes and mimemes, and update their contents when faced.
    By default, agents transmit unadulterated copies of their genomes and
    mimemes, with no error or mutation.
    """

    def __init__(self):
        self.id = uuid4()
        self.genome = None
        self.mimeme = None

    def update(self, other_agent):
        self.genome = other_agent.genome
        self.mimeme = other_agent.mimeme

    def transmit(self):
        return self

    def __repr__(self):
        return self.id.hex[0:4]


class RandomBinaryStringSource(Agent):
    """An agent whose genome and mimeme are random binary strings. The source
    only transmits; it does not update.
    """

    def __init__(self, genome_size=8, mimeme_size=8):
        super(RandomBinaryStringSource, self).__init__()
        self.genome_size = genome_size
        self.mimeme_size = mimeme_size

    def transmit(self):
        self.genome = np.random.randint(0, 2, self.genome_size)
        self.mimeme = np.random.randint(0, 2, self.mimeme_size)
        return self

    def update(self, other_agent):
        pass
