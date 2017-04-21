"""Coordination chatroom game."""

import logging
import random
import time

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


config = get_config()
logger = logging.getLogger(__file__)


def extra_parameters():
    config.register('network', unicode)
    config.register('repeats', int)
    config.register('n', int)


class CoordinationChatroom(dlgr.experiment.Experiment):
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


class Bot(BotBase):
    """A bot conversation demo."""

    GREETINGS = [
        'Hello.',
        'How do you do.',
        'Good day.',
        'Anyone here?',
        'Hi.',
        "What's up?",
    ]

    AVG_TIME_BETWEEN_MESSAGES = 7

    TOTAL_CHAT_TIME = 60

    PERSONALITIES = [
        eliza_chatbot,
        iesha_chatbot,
        rude_chatbot,
        suntsu_chatbot,
        zen_chatbot
    ]

    def get_chat_history(self):
        story = self.driver.find_element_by_id('story')
        return story.text.split('\n')

    def wait_to_send_message(self):
        waiting_time = random.expovariate(1.0 / self.AVG_TIME_BETWEEN_MESSAGES)
        time.sleep(waiting_time)

    def send_message(self, message):
        self.driver.find_element_by_id("reproduction").send_keys(message)
        self.driver.find_element_by_id("send-message").click()

    def leave_chat(self):
        self.driver.find_element_by_id("leave-chat").click()

    def participate(self):
        random.seed(self.worker_id)
        chatbot = random.choice(self.PERSONALITIES)
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, 'send-message')))
        logger.info("Entering participate method")
        start = time.time()
        while (time.time() - start) < self.TOTAL_CHAT_TIME:

            self.wait_to_send_message()
            history = self.get_chat_history()
            logger.info("History: %s" % history)
            if history and history[-1]:
                logger.info("Responding to: %s" % history[-1])
                output = chatbot.respond(history[-1])
            else:
                logger.info("Using random greeting.")
                output = random.choice(self.GREETINGS)
            logger.info("Output: %s" % output)
            self.send_message(output)

        self.leave_chat()
