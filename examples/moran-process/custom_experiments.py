import wallace
from wallace.experiments import Experiment
from wallace.recruiters import SimulatedRecruiter
from custom_sources import WarOfTheGhostsSource
from custom_agents import SimulatedAgent


class SubstitutionCiphersExperiment(Experiment):
    def __init__(self, session):
        super(SubstitutionCiphersExperiment, self).__init__(session)

        self.task = "SubstitutionCipher"
        self.num_agents = 10
        self.num_steps = self.num_agents - 1
        self.network = wallace.networks.FullyConnected(self.session)
        self.process = wallace.processes.RandomWalkFromSource(self.network)
        self.agent_type = SimulatedAgent
        self.recruiter = SimulatedRecruiter

        # Setup for first time experiment is accessed
        if not self.network.sources:
            source = WarOfTheGhostsSource()
            self.network.add_source_global(source)
            print "Added initial source: " + str(source)

        # Open recruitment
        self.recruiter().open_recruitment(self)

    def newcomer_arrival_trigger(self, newcomer):

        self.network.add_agent(newcomer)
        self.network.db.commit()

        # If this is the first participant, link them to the source.
        if len(self.network) == 1:
            source = self.network.sources[0]
            source.connect_to(newcomer)
            self.network.db.commit()

        # Run the next step of the process.
        self.process.step()

        newcomer.receive_all()

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment(self)
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)

    def is_experiment_over(self):
        return len(self.network.vectors) == self.num_agents


if __name__ == "__main__":
    session = wallace.db.init_db(drop_all=False)
    experiment = SubstitutionCiphersExperiment(session)
