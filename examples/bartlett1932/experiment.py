from wallace.networks import Chain
from wallace.processes import RandomWalkFromSource
from wallace.recruiters import PsiTurkRecruiter
from wallace.agents import ReplicatorAgent
from wallace.experiments import Experiment
from wallace.sources import Source


class Bartlett1932(Experiment):
    def __init__(self, session):
        super(Bartlett1932, self).__init__(session)

        self.task = "Transmission chain"
        self.num_agents = 10
        self.num_steps = self.num_agents - 1
        self.agent_type = ReplicatorAgent
        self.network = Chain(self.agent_type, self.session)
        self.process = RandomWalkFromSource(self.network)
        self.recruiter = PsiTurkRecruiter

        # Setup for first time experiment is accessed
        if not self.network.sources:
            source = WarOfTheGhostsSource()
            self.network.add_source_global(source)
            print "Added initial source: " + str(source)

    def newcomer_arrival_trigger(self, newcomer):

        self.network.add_agent(newcomer)

        # If this is the first participant, link them to the source.
        if len(self.network.agents) == 1:
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
        self.network.db.add(agent)
        self.network.db.commit()

        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter().close_recruitment()
        else:
            # Otherwise recruit a new participant.
            self.recruiter().recruit_new_participants(self, n=1)

    def is_experiment_over(self):
        return len(self.network.agents) == self.num_agents


class WarOfTheGhostsSource(Source):
    """A source that transmits the War of Ghosts story from Bartlett (1932).
    """

    __mapper_args__ = {"polymorphic_identity": "war_of_the_ghosts_source"}

    @staticmethod
    def _data():
        with open("static/stimuli/ghosts.md", "r") as f:
            return f.read()
