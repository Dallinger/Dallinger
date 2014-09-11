import processes
import agents
import networks
import db


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
        self.num_steps = 20
        self.network = networks.Chain(self.session)
        self.process = processes.RandomWalkFromSource(self.network)

        # Setup for first time experiment is accessed
        if not self.network.sources:
            source = agents.IdentityFunctionSource()
            self.network.add_node(source)
            print "Added initial source: " + str(source)

    def newcomer_arrival_trigger(self, newcomer):
        if len(self.network) == 1:
            source = self.network.sources[0]
            source.connect_to(newcomer)
        self.process.step()

    def is_experiment_over(self):
        return False


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
