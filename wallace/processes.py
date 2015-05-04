from models import Agent, Source
import random

def random_walk(network):
    """Takes a random walk over a network, starting at a node randomly selected
    from those that receive input from a source."""

    # work out who is going to transmit
    if (not network.transmissions()) or (network.latest_transmission_recipient() is None):
        if len(network.nodes(type=Source)) == 0:
            raise Exception("Cannot start random walk as network does not contain a source.")
        else:
            sender = random.choice(network.nodes(type=Source))
    else:
        sender = network.latest_transmission_recipient()

    # work out who is going to receive
    if len(sender.downstream_nodes(type=Agent)) == 0:
        raise Exception("Cannot execute random walk from {} as it has no downstream agents.".format(sender))
    else:
        receiver = random.choice(sender.downstream_nodes(type=Agent))

    # transmit
    sender.transmit(to_whom=receiver)


def moran_cultural(network):
    """The generalized cultural Moran process plays out over a network. At each
    time step, an individual is chosen to receive information from another
    individual. Nobody dies, but perhaps their ideas do."""

    if not network.transmissions():  # first step, replacer is a source
        replacer = random.choice(network.nodes(type=Source))
        replacer.transmit()
    else:
        replacer = random.choice(network.nodes(type=Agent))
        replaced = random.choice(replacer.downstream_nodes(type=Agent))
        replacer.transmit(what=replacer.infos()[-1], to_whom=replaced)


def moran_sexual(network):
    """The generalized sexual Moran process also plays out over a network. At
    each time step, and individual is chosen for replication and another
    individual is chosen to die. The replication replaces the one who dies.

    For this process to work you need to add a new agent before calling step.
    """

    if not network.transmissions():
        replacer = random.choice(network.nodes(type=Source))
        replacer.transmit()
    else:
        replacer = random.choice(network.nodes(type=Agent)[:-1])
        replaced = random.choice(replacer.downstream_nodes(type=Agent))

        # Find the baby just added
        baby = network.nodes(type=Agent)[-1]

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


def transmit_by_fitness(to_whom=None, what=None, from_whom=Agent):

    parent = None
    potential_parents = to_whom.upstream_nodes(type=from_whom)
    potential_parent_fitnesses = [p.fitness for p in potential_parents]
    potential_parent_probabilities = [(f/(1.0*sum(potential_parent_fitnesses))) for f in potential_parent_fitnesses]

    rnd = random.random()
    temp = 0.0
    for i, probability in enumerate(potential_parent_probabilities):
        temp += probability
        if temp > rnd:
            parent = potential_parents[i]
            break

    parent.transmit(what=what, to_whom=to_whom)
