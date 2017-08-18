"""Bartlett's transmission chain experiment from Remembering (1932)."""

import logging

from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from sqlalchemy import not_

from dallinger.bots import BotBase
from dallinger.networks import DelayedChain
from dallinger.experiment import Experiment
from dallinger.models import Participant


logger = logging.getLogger(__file__)


class Bartlett1932(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Call the same function in the super (see experiments.py in dallinger).

        The models module is imported here because it must be imported at
        runtime.

        A few properties are then overwritten.

        Finally, setup() is called.
        """
        super(Bartlett1932, self).__init__(session)
        import models
        self.models = models
        self.experiment_repeats = 1
        self.initial_recruitment_size = 1
        if session:
            self.setup()

    def setup(self):
        """Setup the networks.

        Setup only does stuff if there are no networks, this is so it only
        runs once at the start of the experiment. It first calls the same
        function in the super (see experiments.py in dallinger). Then it adds a
        source to each network.
        """
        if not self.networks():
            super(Bartlett1932, self).setup()
            for net in self.networks():
                self.models.WarOfTheGhostsSource(network=net)

    def create_network(self):
        """Return a new network."""
        return DelayedChain(max_size=5)

    def add_node_to_network(self, node, network):
        """Add node to the chain and receive transmissions."""
        network.add_node(node)
        parents = node.neighbors(direction="from")
        if len(parents):
            parent = parents[0]
            parent.transmit()
        node.receive()

    def recruit(self):
        """Recruit one participant at a time until all networks are full."""
        if self.networks(full=False):
            self.recruiter().recruit(n=1)

        else:
            self.recruiter().close_recruitment()


class Bot(BotBase):
    """Bot tasks for experiment participation"""

    def participate(self):
        """Finish reading and send text"""
        try:
            logger.info("Entering participate method")
            ready = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'finish-reading')))
            stimulus = self.driver.find_element_by_id('stimulus')
            story = stimulus.find_element_by_id('story')
            story_text = story.text
            logger.info("Stimulus text:")
            logger.info(story_text)
            ready.click()
            submit = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'submit-response')))
            textarea = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'reproduction')))
            textarea.clear()
            text = self.transform_text(story_text)
            logger.info("Transformed text:")
            logger.info(text)
            textarea.send_keys(text)
            submit.click()
            return True
        except TimeoutException:
            return False

    def transform_text(self, text):
        """Experimenter decides how to simulate participant response"""
        return "Some transformation...and %s" % text
