class Experiment(object):
    def __init__(self, session):
        self.task = "Experiment title"
        self.session = session

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
        pass

    def step(self):
        pass

    def is_experiment_over(self):
        return all([self.is_network_full(net) for net in self.networks])

    def bonus(self, participant_uuid=None):
        """Compute the bonus for the given participant."""
        return 0
