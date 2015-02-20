import models
from sqlalchemy import desc
import random


class Process(object):

    def __init__(self, network):
        self.db = network.db
        self.network = network

    def step(self, verbose=True):
        pass

    def is_begun(self):
        """To tell if the process has started yet, check if there have been any
        transmissions."""
        return len(self.db.query(models.Transmission).all()) > 0

    def get_latest_transmission_recipient(self):
        all_transmissions = self.db.query(models.Transmission)\
            .order_by(desc(models.Transmission.transmit_time))\
            .all()

        return next((t.destination for t in all_transmissions
                    if t.destination.status != "failed"),
                    None)


class RandomWalkFromSource(Process):
    """Takes a random walk over a network, starting at a node randomly selected
    from those that receive input from a source."""

    def step(self, verbose=True):

        latest_recipient = self.get_latest_transmission_recipient()

        if (not self.is_begun()) or (latest_recipient is None):
            replacer = random.choice(self.network.sources)
        else:
            replacer = latest_recipient

        options = [v for v in replacer.outgoing_vectors
                   if v.destination.status == "alive"]

        if options:
            replaced = random.choice(options).destination
            replacer.transmit(to_whom=replaced)
            self.db.commit()
        else:
            raise RuntimeError("No outgoing connections to choose from.")


class MoranProcessCultural(Process):
    """The generalized cultural Moran process plays out over a network. At each
    time step, an individual is chosen to receive information from another
    individual. Nobody dies, but perhaps their ideas do."""

    def step(self, verbose=True):

        if not self.is_begun():  # first step, replacer is a source
            replacer = random.choice(self.network.sources)
            replacer.transmit()
        else:
            replacer = random.choice(self.network.agents)
            replaced = random.choice(replacer.outgoing_vectors).destination
            replacer.transmit(to_whom=replaced)
        self.db.commit()


class MoranProcessSexual(Process):
    """The generalized sexual Moran process also plays out over a network. At
    each time step, and individual is chosen for replication and another
    individual is chosen to die. The replication replaces the one who dies."""

    def step(self, verbose=True):

        if not self.is_begun():
            replacer = random.choice(self.network.sources)
            replacer.transmit()
        else:
            replacer = random.choice(self.network.agents)
            replaced = random.choice(replacer.outgoing_vectors).destination

            # Make a baby
            baby = self.network.agent_type_generator()()
            self.network.add_agent(baby)

            # Endow the baby with the ome of the replaced, then sever
            # all ties. :(
            replacer.connect_to(baby)
            replacer.transmit(to_whom=baby)
            baby.receive_all()
            for v in baby.incoming_vectors:
                v.kill()

            # Copy the outgoing connections.
            for v in replaced.outgoing_vectors:
                v.kill()
                baby.connect_to(v.destination)

            self.db.commit()

            # Copy the incoming connections.
            for v in replaced.incoming_vectors:
                v.destination.connect_to(baby)
                v.kill()

            # Kill the agent.
            replaced.kill()

        self.db.commit()
