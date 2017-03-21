"""Bots."""

import logging

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


logger = logging.getLogger(__file__)


class BotBase(object):

    """A bot."""

    def __init__(self, URL):
        logger.info("Starting up bot with URL: %s." % URL)
        self.URL = URL
        self.driver = webdriver.PhantomJS()
        self.driver.set_window_size(1024, 768)
        logger.info("Started PhantomJs webdriver.")

    def sign_up(self):
        """Accept HIT, give consent and start experiment."""
        logger.info("Starting sign up with URL: %s." % self.URL)
        try:
            self.driver.get(self.URL)
            logger.info("Loaded ad page.")
            begin = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, 'btn-primary')))
            begin.click()
            logger.info("Clicked begin experiment button.")
            self.driver.switch_to_window('Popup')
            self.driver.set_window_size(1024, 768)
            logger.info("Switched to experiment popup.")
            consent = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'consent')))
            consent.click()
            logger.info("Clicked consent button.")
            participate = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, 'btn-success')))
            participate.click()
            logger.info("Clicked start button.")
            return True
        except TimeoutException:
            logger.error("Error during experiment sign up.")
            return False

    def participate(self):
        """Participate in the experiment."""
        logger.error("Bot class does not define participate method.")
        raise NotImplementedError

    def sign_off(self):
        """Submit questionnaire and finish."""
        try:
            feedback = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, 'submit-questionnaire')))
            feedback.click()
            logger.info("Clicked submit questionnaire button.")
            self.driver.switch_to_window(self.driver.window_handles[0])
            self.driver.set_window_size(1024, 768)
            logger.info("Switched back to initial window.")
            return True
        except TimeoutException:
            logger.error("Error during experiment sign off.")
            return False

    def run_experiment(self):
        self.sign_up()
        self.participate()
        self.sign_off()
