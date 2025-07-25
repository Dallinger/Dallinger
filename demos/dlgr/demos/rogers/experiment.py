"""Replicate Rogers' paradox by simulating evolution with people."""

import random

import six

from dallinger.config import get_config
from dallinger.experiment import Experiment
from dallinger.information import Meme
from dallinger.models import Node, Participant
from dallinger.networks import DiscreteGenerational


def extra_parameters():
    config = get_config()
    types = {
        "experiment_repeats": int,
        "practice_repeats": int,
        "catch_repeats": int,
        "practice_difficulty": float,
        "catch_difficulty": float,
        "difficulties": six.text_type,  # comma separated floats
        "min_acceptable_performance": float,
        "generations": int,
        "generation_size": int,
        "bonus_payment": float,
    }

    for key in types:
        config.register(key, types[key])


class RogersExperiment(Experiment):
    """The experiment class."""

    def __init__(self, session=None):
        """Call the same function in the super (see experiments.py in dallinger).

        The models module is imported here because it must be imported at
        runtime.

        A few properties are then overwritten.

        Finally, setup() is called.
        """
        super(RogersExperiment, self).__init__(session)
        from . import models

        self.models = models
        self.known_classes["LearningGene"] = self.models.LearningGene

        if session and not self.networks():
            self.setup()

    def configure(self):
        config = get_config()
        self.experiment_repeats = config.get("experiment_repeats")
        self.practice_repeats = config.get("practice_repeats")
        self.catch_repeats = config.get(
            "catch_repeats", 0
        )  # a subset of experiment repeats
        self.practice_difficulty = config.get("practice_difficulty")

        self.difficulties = [
            float(f.strip()) for f in config.get("difficulties").split(",")
        ] * self.experiment_repeats

        self.catch_difficulty = config.get("catch_difficulty")
        self.min_acceptable_performance = config.get("min_acceptable_performance")
        self.generation_size = config.get("generation_size")
        self.generations = config.get("generations")
        self.bonus_payment = config.get("bonus_payment")
        self.initial_recruitment_size = self.generation_size

    @property
    def public_properties(self):
        return {
            "practice_repeats": self.practice_repeats,
            "experiment_repeats": self.experiment_repeats,
        }

    def setup(self):
        """First time setup."""
        super(RogersExperiment, self).setup()

        for net in random.sample(self.networks(role="experiment"), self.catch_repeats):
            net.role = "catch"

        for net in self.networks():
            source = self.models.RogersSource(network=net)
            source.create_information()
            net.max_size = net.max_size + 1  # make room for environment node.
            env = self.models.RogersEnvironment(network=net)
            env.proportion = self.color_proportion_for_network(net)
            env.create_information()
        self.session.commit()

    def color_proportion_for_network(self, net):
        if net.role == "practice":
            return self.practice_difficulty
        if net.role == "catch":
            return self.catch_difficulty
        if net.role == "experiment":
            return self.difficulties[self.networks(role="experiment").index(net)]

    def create_network(self):
        """Create a new network."""
        return DiscreteGenerational(
            generations=self.generations,
            generation_size=self.generation_size,
            initial_source=True,
        )

    def create_node(self, network, participant):
        """Make a new node for participants."""
        return self.models.RogersAgent(network=network, participant=participant)

    def info_post_request(self, node, info):
        """Run whenever an info is created."""
        node.calculate_fitness()

    def submission_successful(self, participant):
        """Run when a participant submits successfully."""
        num_approved = len(
            self.session.query(Participant).filter_by(status="approved").all()
        )
        current_generation = participant.nodes()[0].generation
        if (
            num_approved % self.generation_size == 0
            and (current_generation % 10 + 1) == 0  # noqa
        ):
            for e in self.models.RogersEnvironment.query.all():
                e.step()

    def recruit(self):
        """Recruit participants if necessary."""
        num_approved = len(
            self.session.query(Participant).filter_by(status="approved").all()
        )
        end_of_generation = num_approved % self.generation_size == 0
        complete = num_approved >= (self.generations * self.generation_size)
        if complete:
            self.log("All networks full: closing recruitment", "-----")
            self.recruiter.close_recruitment()
        elif end_of_generation:
            self.log("generation finished, recruiting another")
            self.recruiter.recruit(n=self.generation_size)

    def bonus(self, participant):
        """Calculate a participants bonus."""
        scores = [
            n.score for n in participant.nodes() if n.network.role == "experiment"
        ]
        average = float(sum(scores)) / float(len(scores))

        bonus = round(max(0.0, ((average - 0.5) * 2)) * self.bonus_payment, 2)
        return bonus

    def attention_check(self, participant=None):
        """Check a participant paid attention."""
        if self.catch_repeats == 0:
            return True

        scores = [n.score for n in participant.nodes() if n.network.role == "catch"]
        avg = float(sum(scores)) / float(len(scores))
        return avg >= self.min_acceptable_performance

    def data_check(self, participant):
        """Check a participants data."""
        nodes = self.session.query(Node).filter_by(participant_id=participant.id).all()

        if len(nodes) != self.experiment_repeats + self.practice_repeats:
            print(
                "Error: Participant has {} nodes. Data check failed".format(len(nodes))
            )
            return False

        nets = [n.network_id for n in nodes]
        if len(nets) != len(set(nets)):
            print(
                "Error: Participant participated in the same network \
                   multiple times. Data check failed"
            )
            return False

        if None in [n.fitness for n in nodes]:
            print(
                "Error: some of participants nodes are missing a fitness. \
                   Data check failed."
            )
            return False

        if None in [n.score for n in nodes]:
            print(
                "Error: some of participants nodes are missing a score. \
                   Data check failed"
            )
            return False
        return True

    def add_node_to_network(self, node, network):
        """Add participant's node to a network."""
        network.add_node(node)
        node.receive()

        environment = network.nodes(type=self.models.RogersEnvironment)[0]
        environment.connect(whom=node)

        gene = node.infos(type=self.models.LearningGene)[0].contents
        if gene == "social":
            agent_model = self.models.RogersAgent
            prev_agents = agent_model.query.filter_by(
                failed=False, network_id=network.id, generation=node.generation - 1
            ).all()
            parent = random.choice(prev_agents)
            parent.connect(whom=node)
            parent.transmit(what=Meme, to_whom=node)
        elif gene == "asocial":
            environment.transmit(to_whom=node)
        else:
            raise ValueError(
                "{} has invalid learning gene value of {}".format(node, gene)
            )
        node.receive()
