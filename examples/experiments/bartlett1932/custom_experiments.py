import wallace
from custom_sources import WarOfTheGhostsSource


class Bartlett1932(wallace.experiments.Experiment):
    def __init__(self, session):
        super(Bartlett1932, self).__init__(session)

        self.task = "Transmission chain"
        self.num_agents = 10
        self.num_steps = self.num_agents - 1
        self.network = wallace.networks.Chain(self.session)
        self.process = wallace.processes.RandomWalkFromSource(self.network)
        self.recruiter = wallace.recruiters.PsiTurkRecruiter
        self.agent_type = wallace.agents.Agent

        # Setup for first time experiment is accessed
        if not self.network.sources:
            source = WarOfTheGhostsSource()
            self.network.add_node(source)
            print "Added initial source: " + str(source)

    def newcomer_arrival_trigger(self, newcomer):

        # Set the newcomer to invisible.
        newcomer.is_visible = False

        self.network.add_agent(newcomer)

        # If this is the first participant, link them to the source.
        if len(self.network) == 0:
            source = self.network.sources[0]
            source.connect_to(newcomer)
            self.network.db.commit()

        # Run the next step of the process.
        self.process.step()

    def transmission_reception_trigger(self, transmissions):
        # Mark transmissions as received
        for t in transmissions:
            t.mark_received()

    def information_creation_trigger(self, info):

        agent = info.origin
        agent.is_visible = True
        self.network.db.add(agent)
        self.network.db.commit()

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment()
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(n=1)

    def is_experiment_over(self):
        return len(self.network.links) == self.num_agents
