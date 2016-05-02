"""Replicate Rogers' paradox by simulating evolution with people."""

from wallace.experiments import Experiment
from wallace.information import Gene, Meme, State
from wallace.nodes import Source, Agent, Environment
from wallace.networks import DiscreteGenerational
from wallace.models import Node, Network, Participant
from wallace import transformations
from sqlalchemy import Integer, Float
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.sql.expression import cast
from sqlalchemy import and_
from operator import attrgetter
import random


class RogersExperiment(Experiment):
    """The experiment class."""

    def __init__(self, session):
        """Create the experiment."""
        super(RogersExperiment, self).__init__(session)
        self.verbose = False
        self.experiment_repeats = 1
        self.practice_repeats = 0
        self.catch_repeats = 0  # a subset of experiment repeats
        self.practice_difficulty = 0.80
        self.difficulties = [0.525, 0.5625, 0.65] * self.experiment_repeats
        self.catch_difficulty = 0.80
        self.min_acceptable_performance = 10 / float(12)
        self.generation_size = 40
        self.network = lambda: DiscreteGenerational(
            generations=4, generation_size=self.generation_size,
            initial_source=True)
        self.bonus_payment = 1.0
        self.initial_recruitment_size = self.generation_size
        self.known_classes["LearningGene"] = LearningGene

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
            source = RogersSource(network=net)
            source.create_information()
            if net.role == "practice":
                env = RogersEnvironment(network=net)
                env.create_state(proportion=self.practice_difficulty)
            if net.role == "catch":
                env = RogersEnvironment(network=net)
                env.create_state(proportion=self.catch_difficulty)
            if net.role == "experiment":
                difficulty = self.difficulties[self.networks(role="experiment")
                                               .index(net)]
                env = RogersEnvironment(network=net)
                env.create_state(proportion=difficulty)

    def node_type(self, network):
        """What class of agent to create."""
        if network.role == "practice" or network.role == "catch":
            return RogersAgentFounder
        elif network.size(type=Agent) < network.generation_size:
            return RogersAgentFounder
        else:
            return RogersAgent

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

        gene = node.infos(type=LearningGene)[0].contents
        if (gene == "social"):
            prev_agents = RogersAgent.query\
                .filter(and_(RogersAgent.failed == False,
                             RogersAgent.network_id == network.id,
                             RogersAgent.generation == node.generation - 1))\
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


class LearningGene(Gene):
    """The Learning Gene."""

    __mapper_args__ = {"polymorphic_identity": "learning_gene"}

    def _mutated_contents(self):
        alleles = ["social", "asocial"]
        return random.choice([a for a in alleles if a != self.contents])


class RogersSource(Source):
    """A source that initializes agents as asocial learners."""

    __mapper_args__ = {"polymorphic_identity": "rogers_source"}

    def create_information(self):
        """Create a new learning gene."""
        if len(self.infos()) == 0:
            LearningGene(
                origin=self,
                contents="asocial")

    def _what(self):
        """Transmit a learning gene by default."""
        return self.infos(type=LearningGene)[0]


class RogersAgent(Agent):
    """The Rogers Agent."""

    __mapper_args__ = {"polymorphic_identity": "rogers_agent"}

    @hybrid_property
    def generation(self):
        """Convert property2 to genertion."""
        return int(self.property2)

    @generation.setter
    def generation(self, generation):
        """Make generation settable."""
        self.property2 = repr(generation)

    @generation.expression
    def generation(self):
        """Make generation queryable."""
        return cast(self.property2, Integer)

    @hybrid_property
    def score(self):
        """Convert property3 to score."""
        return int(self.property3)

    @score.setter
    def score(self, score):
        """Mark score settable."""
        self.property3 = repr(score)

    @score.expression
    def score(self):
        """Make score queryable."""
        return cast(self.property3, Integer)

    @hybrid_property
    def proportion(self):
        """Make property4 proportion."""
        return float(self.property4)

    @proportion.setter
    def proportion(self, proportion):
        """Make proportion settable."""
        self.property4 = repr(proportion)

    @proportion.expression
    def proportion(self):
        """Make proportion queryable."""
        return cast(self.property4, Float)

    def calculate_fitness(self):
        """Calculcate your fitness."""
        if self.fitness is not None:
            raise Exception("You are calculating the fitness of agent {}, "
                            .format(self.id) +
                            "but they already have a fitness")
        infos = self.infos()

        said_blue = ([i for i in infos if
                      isinstance(i, Meme)][0].contents == "blue")
        proportion = float(
            max(State.query.filter_by(network_id=self.network_id).all(),
                key=attrgetter('creation_time')).contents)
        self.proportion = proportion
        is_blue = proportion > 0.5

        if said_blue is is_blue:
            self.score = 1
        else:
            self.score = 0

        is_asocial = [
            i for i in infos if isinstance(i, LearningGene)
        ][0].contents == "asocial"
        e = 2
        b = 1
        c = 0.3 * b
        baseline = c + 0.0001

        self.fitness = (baseline + self.score * b - is_asocial * c) ** e

    def update(self, infos):
        """Process received infos."""
        for info_in in infos:
            if isinstance(info_in, LearningGene):
                if random.random() < 0.10:
                    self.mutate(info_in)
                else:
                    self.replicate(info_in)

    def _what(self):
        return self.infos(type=LearningGene)[0]


class RogersAgentFounder(RogersAgent):
    """The Rogers Agent Founder.

    It is like Rogers Agent except it cannot mutate.
    """

    __mapper_args__ = {"polymorphic_identity": "rogers_agent_founder"}

    def update(self, infos):
        """Process received infos."""
        for info in infos:
            if isinstance(info, LearningGene):
                self.replicate(info)


class RogersEnvironment(Environment):
    """The Rogers environment."""

    __mapper_args__ = {"polymorphic_identity": "rogers_environment"}

    def create_state(self, proportion):
        """Create an environmental state."""
        if random.random() < 0.5:
            proportion = 1 - proportion
        State(origin=self, contents=proportion)

    def step(self):
        """Prompt the environment to change."""
        current_state = max(self.infos(type=State),
                            key=attrgetter('creation_time'))
        current_contents = float(current_state.contents)
        new_contents = 1 - current_contents
        info_out = State(origin=self, contents=new_contents)
        transformations.Mutation(info_in=current_state, info_out=info_out)
