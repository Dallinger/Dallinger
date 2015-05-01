from wallace.models import Network, Node, Agent
import random


class Experiment(object):
    def __init__(self, session):
        from recruiters import PsiTurkRecruiter
        self.task = "Experiment title"
        self.session = session
        self.num_repeats_practice = 0
        self.num_repeats_experiment = 0
        self.recruiter = PsiTurkRecruiter

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

    def create_agent_trigger(self, agent, network):
        network.add_agent(agent)
        self.process(network).step()

    def assign_agent_to_participant(self, participant_uuid):

        num_networks_participated_in = sum(
            [net.has_participant(participant_uuid) for net in self.networks])

        if num_networks_participated_in < self.num_repeats_practice:
            practice_net = self.networks[num_networks_participated_in]
            if not practice_net.full():
                legal_networks = [practice_net]
            else:
                legal_networks = []

        else:
            legal_networks = [net for net in self.networks if
                              ((not net.full()) and
                               (not net.has_participant(participant_uuid)))]

        if legal_networks:
            # Figure out which network to place the next newcomer in.
            plenitude = [len(net.nodes(type=Agent)) for net in legal_networks]
            idxs = [i for i, x in enumerate(plenitude) if x == min(plenitude)]
            net = legal_networks[random.choice(idxs)]

            # Generate the right kind of newcomer.
            try:
                assert(issubclass(self.agent, Node))
                atg = lambda network=net: self.agent
            except:
                atg = self.agent

            newcomer_type = atg(network=net)
            newcomer = newcomer_type(participant_uuid=participant_uuid)
            self.save(newcomer)

            # Add the newcomer to the network.
            net.add(newcomer)
            self.create_agent_trigger(agent=newcomer, network=net)
            return newcomer
        else:
            raise Exception

    def is_experiment_over(self):
        return all([net.full() for net in self.networks])

    def bonus(self, participant_uuid=None):
        """Compute the bonus for the given participant."""
        return 0
