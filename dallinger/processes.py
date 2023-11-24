"""Processes manipulate networks and their parts."""

import random

from .nodes import Agent, Source


def random_walk(network):
    """Take a random walk from a source.

    Start at a node randomly selected from those that receive input from a
    source. At each step, transmit to a randomly-selected downstream node.
    """
    latest = network.latest_transmission_recipient()

    if not network.transmissions() or latest is None:
        sender = random.choice(network.nodes(type=Source))
    else:
        sender = latest

    receiver = random.choice(sender.neighbors(direction="to", type=Agent))

    sender.transmit(to_whom=receiver)


def moran_cultural(network):
    """Generalized cultural Moran process.

    At eachtime step, an individual is chosen to receive information from
    another individual. Nobody dies, but perhaps their ideas do.
    """
    if not network.transmissions():  # first step, replacer is a source
        replacer = random.choice(network.nodes(type=Source))
        replacer.transmit()
    else:
        replacer = random.choice(network.nodes(type=Agent))
        replaced = random.choice(replacer.neighbors(direction="to", type=Agent))

        from operator import attrgetter

        replacer.transmit(
            what=max(replacer.infos(), key=attrgetter("creation_time")),
            to_whom=replaced,
        )


def moran_sexual(network):
    """The generalized sexual Moran process.

    Ateach time step, and individual is chosen for replication and another
    individual is chosen to die. The replication replaces the one who dies.
    For this process to work you need to add a new agent before calling step.
    """
    if not network.transmissions():
        replacer = random.choice(network.nodes(type=Source))
        replacer.transmit()
    else:
        from operator import attrgetter

        agents = network.nodes(type=Agent)
        baby = max(agents, key=attrgetter("creation_time"))
        agents = [a for a in agents if a.id != baby.id]
        replacer = random.choice(agents)
        replaced = random.choice(replacer.neighbors(direction="to", type=Agent))

        # Give the baby the same outgoing connections as the replaced.
        for node in replaced.neighbors(direction="to"):
            baby.connect(direction="to", whom=node)

        # Give the baby the same incoming connections as the replaced.
        for node in replaced.neighbors(direction="from"):
            node.connect(direction="to", whom=baby)

        # Kill the replaced agent.
        replaced.fail()

        # Endow the baby with the ome of the replacer.
        replacer.transmit(to_whom=baby)


def transmit_by_fitness(from_whom, to_whom=None, what=None):
    """Choose a parent with probability proportional to their fitness."""
    parents = from_whom
    parent_fs = [p.fitness for p in parents]
    parent_probs = [(f / (1.0 * sum(parent_fs))) for f in parent_fs]

    rnd = random.random()
    temp = 0.0
    for i, probability in enumerate(parent_probs):
        temp += probability
        if temp > rnd:
            parent = parents[i]
            break

    parent.transmit(what=what, to_whom=to_whom)
