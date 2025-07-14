"""Monte Carlo Markov Chains with people."""

import random
import time
from operator import attrgetter

from flask import Response
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from dallinger import db
from dallinger.bots import BotBase
from dallinger.experiment import Experiment, experiment_route
from dallinger.networks import Chain


class MCMCP(Experiment):
    """Define the structure of the experiment."""

    experiment_repeats = 1
    trials_per_participant = 10

    def create_node(self, network, participant):
        """Create a node for a participant."""
        from . import models

        return models.MCMCPAgent(network=network, participant=participant)

    def setup(self):
        """Setup the networks."""
        from . import models

        if not self.networks():
            super(MCMCP, self).setup()
            for net in self.networks():
                models.AnimalSource(network=net)
            db.session.commit()

    def create_network(self):
        """Create a new network."""
        return Chain(max_size=10)

    def get_network_for_participant(self, participant):
        if len(participant.nodes(failed="all")) < self.trials_per_participant:
            return random.choice(self.networks())
        else:
            return None

    def add_node_to_network(self, node, network):
        """When a node is created it is added to the chain (see Chain in networks.py)
        and it receives any transmissions."""
        network.add_node(node)
        parent = node.neighbors(direction="from")[0]
        parent.transmit()
        node.receive()

    def data_check(self, participant):
        """Make sure each trial contains exactly one chosen info."""
        infos = participant.infos()
        return len([info for info in infos if info.chosen]) * 2 == len(infos)

    @experiment_route("/choice/<int:node_id>/<int:choice>", methods=["POST"])
    @classmethod
    def choice(cls, node_id, choice):
        from dallinger import db

        from . import models

        try:
            exp = MCMCP(db.session)
            node = models.Agent.query.get(node_id)
            infos = node.infos()

            if choice == 0:
                info = max(infos, key=attrgetter("id"))
            elif choice == 1:
                info = min(infos, key=attrgetter("id"))
            else:
                raise ValueError("Choice must be 1 or 0")

            info.chosen = True
            exp.save()

            return Response(status=200, mimetype="application/json")
        except Exception:
            return Response(status=403, mimetype="application/json")


class Bot(BotBase):
    """Bot tasks for experiment participation"""

    def participate(self):
        """Finish reading and send text"""
        try:
            while True:
                left = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "left_button"))
                )
                right = WebDriverWait(self.driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "right_button"))
                )

                random.choice((left, right)).click()
                time.sleep(1.0)
        except TimeoutException:
            return False
