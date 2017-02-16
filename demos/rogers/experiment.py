"""Replicate Rogers' paradox by simulating evolution with people."""

from dallinger.experiments import Experiment
from dallinger.information import Meme
from dallinger.nodes import Agent, Environment
from dallinger.networks import DiscreteGenerational
from dallinger.models import Node, Network, Participant
from sqlalchemy.sql.expression import false
from sqlalchemy import and_
import random


class RogersExperiment(Experiment):
    """The experiment class."""

    def __init__(self, session):
        """Call the same function in the super (see experiments.py in dallinger).

        The models module is imported here because it must be imported at
        runtime.

        A few properties are then overwritten.

        Finally, setup() is called.
        """
        super(RogersExperiment, self).__init__(session)
        import models
        self.models = models
        self.verbose = False
        self.experiment_repeats = 1
        self.practice_repeats = 0
        self.catch_repeats = 0  # a subset of experiment repeats
        self.practice_difficulty = 0.80
        self.difficulties = [0.525, 0.5625, 0.65] * self.experiment_repeats
        self.catch_difficulty = 0.80
        self.min_acceptable_performance = 10 / float(12)
        self.generation_size = 40
        self.bonus_payment = 1.0
        self.initial_recruitment_size = self.generation_size
        self.known_classes["LearningGene"] = self.models.LearningGene

        if not self.networks():
            self.setup()
        self.save()

    def setup(self):
        """First time setup."""
        super(RogersExperiment, self).setup()

        for net in random.sample(self.networks(role="experiment"),
                                 self.catch_repeats):
            net.role = "catch"

        for net in self.networks():
            source = self.models.RogersSource(network=net)
            source.create_information()
            if net.role == "practice":
                env = self.models.RogersEnvironment(network=net)
                env.create_state(proportion=self.practice_difficulty)
            if net.role == "catch":
                env = self.models.RogersEnvironment(network=net)
                env.create_state(proportion=self.catch_difficulty)
            if net.role == "experiment":
                difficulty = self.difficulties[self.networks(role="experiment")
                                               .index(net)]
                env = self.models.RogersEnvironment(network=net)
                env.create_state(proportion=difficulty)

    def create_network(self):
        """Create a new network."""
        return DiscreteGenerational(
            generations=4, generation_size=self.generation_size,
            initial_source=True)

    def create_node(self, network, participant):
        """Make a new node for participants."""
        if network.role == "practice" or network.role == "catch":
            return self.models.RogersAgentFounder(network=network,
                                                  participant=participant)
        elif network.size(type=Agent) < network.generation_size:
            return self.models.RogersAgentFounder(network=network,
                                                  participant=participant)
        else:
            return self.models.RogersAgent(network=network,
                                           participant=participant)

    def info_post_request(self, node, info):
        """Run whenever an info is created."""
        node.calculate_fitness()

    def submission_successful(self, participant):
        """Run when a participant submits successfully."""
        key = participant.uniqueid[0:5]

        finished_participants = Participant.query.filter_by(status=101).all()
        num_finished_participants = len(finished_participants)
        current_generation = int((num_finished_participants - 1) /
                                 float(self.generation_size))

        if num_finished_participants % self.generation_size == 0:
            if (current_generation + 1) % 10 == 0:
                self.log("Participant was final particpant in generation {}: \
                          environment stepping"
                         .format(current_generation), key)
                environments = Environment.query.all()
                for e in environments:
                    e.step()
            else:
                self.log("Participant was final participant in generation {}: \
                          not stepping".format(current_generation), key)
        else:
            self.log("Participant was not final in generation {}: \
                      not stepping".format(current_generation), key)

    def recruit(self):
        """Recruit more participants."""
        participants = Participant.query.\
            with_entities(Participant.status).all()

        # if all networks are full, close recruitment,
        if not self.networks(full=False):
            print "All networks are full, closing recruitment."
            self.recruiter().close_recruitment()

        # if anyone is still working, don't recruit
        elif [p for p in participants if p.status < 100]:
            print "People are still participating: not recruiting."

        # we only need to recruit if the current generation is complete
        elif (len([p for p in participants if p.status == 101]) %
              self.generation_size) == 0:
            print "Recruiting another generation."
            self.recruiter().recruit_participants(n=self.generation_size)
        # otherwise do nothing
        else:
            print "not recruiting."

    def bonus(self, participant=None):
        """Calculate a participants bonus."""
        if participant is None:
            raise(ValueError("You must specify the participant to \
                              calculate the bonus."))
        participant_id = participant.uniqueid
        key = participant_id[0:5]

        nodes = Node.query.join(Node.network)\
                    .filter(and_(Node.participant_id == participant_id,
                                 Network.role == "experiment"))\
                    .all()

        if len(nodes) == 0:
            self.log("Participant has 0 nodes - cannot calculate bonus!", key)
            return 0
        self.log("calculating bonus...", key)
        score = [node.score for node in nodes]
        average = float(sum(score)) / float(len(score))
        bonus = round(max(0.0, ((average - 0.5) * 2)) * self.bonus_payment, 2)
        self.log("bonus calculated, returning {}".format(bonus), key)
        return bonus

    def attention_check(self, participant=None):
        """Check a participant paid attention."""
        participant_nodes = Node.query.join(Node.network)\
            .filter(and_(Node.participant_id == participant.uniqueid,
                         Network.role == "catch"))\
            .all()
        scores = [n.score for n in participant_nodes]

        if participant_nodes:
            avg = sum(scores) / float(len(scores))
        else:
            return True

        is_passing = avg >= self.min_acceptable_performance
        return is_passing

    def data_check(self, participant):
        """Check a participants data."""
        participant_id = participant.uniqueid

        nodes = Node.query.filter_by(participant_id=participant_id).all()

        if len(nodes) != self.experiment_repeats + self.practice_repeats:
            print("Error: Participant has {} nodes. Data check failed"
                  .format(len(nodes)))
            return False

        nets = [n.network_id for n in nodes]
        if len(nets) != len(set(nets)):
            print "Error: Participant participated in the same network \
                   multiple times. Data check failed"
            return False

        if None in [n.fitness for n in nodes]:
            print "Error: some of participants nodes are missing a fitness. \
                   Data check failed."
            return False

        if None in [n.score for n in nodes]:
            print "Error: some of participants nodes are missing a score. \
                   Data check failed"
            return False
        return True

    def add_node_to_network(self, node, network):
        """Add participant's node to a network."""
        network.add_node(node)
        node.receive()

        environment = network.nodes(type=Environment)[0]
        environment.connect(whom=node)

        gene = node.infos(type=self.models.LearningGene)[0].contents
        if (gene == "social"):
            agent_model = self.models.RogersAgent
            prev_agents = agent_model.query\
                .filter(and_(agent_model.failed == false(),
                             agent_model.network_id == network.id,
                             agent_model.generation == node.generation - 1))\
                .all()
            parent = random.choice(prev_agents)
            parent.connect(whom=node)
            parent.transmit(what=Meme, to_whom=node)
        elif (gene == "asocial"):
            environment.transmit(to_whom=node)
        else:
            raise ValueError("{} has invalid learning gene value of {}"
                             .format(node, gene))
        node.receive()
