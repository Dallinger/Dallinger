import processes
import agents
import networks
import recruiters


class Experiment(object):
    def __init__(self, session):
        self.task = "Experiment title"
        self.session = session

    def add_sources(self):
        pass

    def step(self):
        pass


class Demo1(Experiment):
    def __init__(self, session):
        super(Demo1, self).__init__(session)
        self.task = "Transmission chain"
        self.num_agents = 10
        self.num_steps = self.num_agents - 1
        self.network = networks.Chain(self.session)
        self.process = processes.RandomWalkFromSource(self.network)
        self.recruiter = recruiters.BotoRecruiter()

        # Setup for first time experiment is accessed
        if not self.network.sources:
            source = agents.SinusoidalFunctionSource()
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
        if self.is_experiment_over():
            # If the experiment is over, stop recruiting and export the data.
            self.recruiter.close_recruitment()
        else:
            # Otherwise recruit a new participant.
            self.recruiter.recruit_new_participants(n=1)

    def is_experiment_over(self):
        return self.network.links == self.num_agents


class Demo2(Experiment):
    def __init__(self, session):
        super(Demo2, self).__init__(session)
        self.task = "Moran process over scale free network"
        self.num_agents = 10
        self.num_steps = 20
        self.network = networks.Chain(self.session)
        self.process = processes.MoranProcess(self.network)

        # Setup for first time experiment is accessed
        if not self.network.sources:
            source = agents.RandomBinaryStringSource()
            self.network.add_node(source)
            print "Added initial source: " + str(source)

    def newcomer_arrival_trigger(self, newcomer):
        # Seed newcomer with info from source
        source = self.network.sources[0]
        source.connect_to(newcomer)
        self.network.trigger_source(source)
        newcomer.receive_all()

        # Run the process
        self.process.step()

    def is_experiment_over(self):
        return False
