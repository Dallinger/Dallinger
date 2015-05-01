from models import Network


class Experiment(object):
    def __init__(self, session):
        self.task = "Experiment title"
        self.session = session
        self.num_repeats_practice = 0
        self.num_repeats_experiment = 0

    def setup(self):
        # Create the networks iff they don't already exist.
        self.networks = Network.query.all()
        if not self.networks:
            repeats = self.num_repeats_experiment + self.num_repeats_practice
            for i in range(repeats):
                self.save(self.network())
        self.networks = Network.query.all()

    def save(self, *objects):
        if len(objects) > 0:
            self.session.add_all(objects)
        self.session.commit()

    def newcomer_arrival_trigger(self, newcomer):
        pass

    def transmission_reception_trigger(self, transmissions):
        # Mark transmissions as received
        for t in transmissions:
            t.mark_received()

    def information_creation_trigger(self, info):
        self.save(info.origin)

    def step(self):
        pass

    def is_experiment_over(self):
        return all([self.is_network_full(net) for net in self.networks])

    def bonus(self, participant_uuid=None):
        """Compute the bonus for the given participant."""
        return 0
