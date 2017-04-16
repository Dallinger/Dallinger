"""Coordination chatroom game."""

import logging
import random
from time import sleep

from nltk.chat.eliza import eliza_chatbot
from nltk.chat.iesha import iesha_chatbot
from nltk.chat.rude import rude_chatbot
from nltk.chat.suntsu import suntsu_chatbot
from nltk.chat.zen import zen_chatbot

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import dallinger as dlgr
from dallinger.bots import BotBase
from dallinger.compat import unicode
from dallinger.config import get_config
from dallinger.experiments import Experiment


config = get_config()
logger = logging.getLogger(__file__)


def extra_parameters():
    config.register('network', unicode)
    config.register('repeats', int)
    config.register('n', int)


class CoordinationChatroom(Experiment):
    """Define the structure of the experiment."""

    def __init__(self, session=None):
        """Initialize the experiment."""
        super(CoordinationChatroom, self).__init__(session)
        self.experiment_repeats = repeats = config.get('repeats')
        self.quorum = config.get('n')
        # Recruit for all networks at once
        self.initial_recruitment_size = repeats * self.quorum
        self.config = config
        if not self.config.ready:
            self.config.load()
        if session:
            self.setup()

    def create_network(self):
        """Create a new network by reading the configuration file."""
        class_ = getattr(
            dlgr.networks,
            self.config.get('network')
        )
        return class_(max_size=self.quorum)

    def choose_network(self, networks, participant):
        # Choose first available network rather than random
        return networks[0]

    def info_post_request(self, node, info):
        """Run when a request to create an info is complete."""
        for agent in node.neighbors():
            node.transmit(what=info, to_whom=agent)

    def create_node(self, participant, network):
        """Create a node for a participant."""
        return dlgr.nodes.Agent(network=network, participant=participant)


GREETINGS = ['Hello.',
             'How do you do.',
             'Good day.',
             'Anyone here?',
             'Hi.',
             "What's up?"]

AVG_TIME_BETWEEN_MESSAGES = 7

TOTAL_CHAT_TIME = 60

BOTS = [eliza_chatbot, iesha_chatbot, rude_chatbot, suntsu_chatbot, zen_chatbot]

class Bot(BotBase):
    """A bot conversation demo."""

    def participate(self):
        random.seed(self.worker_id)
        chatbot = random.choice(BOTS)
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'send-message')))
        logger.info("Entering participate method")
        chat_time = TOTAL_CHAT_TIME
        while chat_time > 0:
            waiting_time = int(random.expovariate(1.0/AVG_TIME_BETWEEN_MESSAGES)) + 1
            sleep(waiting_time)
            chat_time = chat_time - waiting_time
            story = self.driver.find_element_by_id('story')
            history = story.text.split('\n')
            logger.info("History: %s" % history)
            if history and history[-1]:
                logger.info("Responding to: %s" % history[-1])
                output = chatbot.respond(history[-1])
            else:
                logger.info("Using random greeting.")
                output = random.choice(GREETINGS)
            logger.info("Output: %s" % output)
            self.driver.execute_script('$("#reproduction").val("%s")' %
                                       output)
            self.driver.execute_script('$("#send-message").click()')
        self.driver.execute_script('leave_chatroom()')
