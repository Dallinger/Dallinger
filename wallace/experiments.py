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


class Demo2(Experiment):
    def __init__(self, session):
        super(Demo2, self).__init__(session)
        self.task = "Demo2"
        self.num_agents = 20
        self.num_steps = 100
        self.network = networks.ScaleFree(self.session, self.num_agents)
        self.process = processes.MoranProcess(self.network)

    def add_and_trigger_sources(self):
        # Add a binary string source and transmit to everyone
        source = agents.RandomBinaryStringSource()
        self.network.add_global_source(source)
        self.network.trigger_source(source)
