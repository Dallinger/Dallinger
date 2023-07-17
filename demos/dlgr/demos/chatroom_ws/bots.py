"""Chatroom Bots"""

import logging
import random
import time

from nltk.chat.eliza import eliza_chatbot
from nltk.chat.iesha import iesha_chatbot
from nltk.chat.rude import rude_chatbot
from nltk.chat.suntsu import suntsu_chatbot
from nltk.chat.zen import zen_chatbot
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from dallinger.bots import BotBase

logger = logging.getLogger(__file__)


class Bot(BotBase):
    """A bot conversation demo."""

    GREETINGS = [
        "Hello.",
        "How do you do.",
        "Good day.",
        "Anyone here?",
        "Hi.",
        "What's up?",
    ]

    AVG_TIME_BETWEEN_MESSAGES = 7

    TOTAL_CHAT_TIME = 60

    PERSONALITIES = [
        eliza_chatbot,
        iesha_chatbot,
        rude_chatbot,
        suntsu_chatbot,
        zen_chatbot,
    ]

    def get_chat_history(self):
        story = self.driver.find_element("id", "story")
        return story.text.split("\n")

    def wait_to_send_message(self):
        waiting_time = random.expovariate(1.0 / self.AVG_TIME_BETWEEN_MESSAGES)
        time.sleep(waiting_time)

    def send_message(self, message):
        self.driver.find_element("id", "reproduction").send_keys(message)
        self.driver.find_element("id", "send-message").click()

    def leave_chat(self):
        self.driver.find_element("id", "leave-chat").click()

    def participate(self):
        random.seed(self.worker_id)
        chatbot = random.choice(self.PERSONALITIES)
        WebDriverWait(self.driver, 10).until(
            EC.element_to_be_clickable((By.ID, "send-message"))
        )
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
