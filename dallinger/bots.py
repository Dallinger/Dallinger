"""Bots."""

import logging
from cached_property import cached_property
from urlparse import urlparse, parse_qs

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

logger = logging.getLogger(__file__)


class BotBase(object):
    """A base class for Bots that works with the built-in demos."""

    def __init__(self, URL, assignment_id='', worker_id=''):
        logger.info("Creating bot with URL: %s." % URL)
        self.URL = URL

        parts = urlparse(URL)
        query = parse_qs(parts.query)
        if not assignment_id:
            assignment_id = query.get('assignmentId', [''])[0]
        self.assignment_id = assignment_id
        if not worker_id:
            worker_id = query.get('workerId', [''])[0]
        self.worker_id = worker_id
        self.unique_id = worker_id + ':' + assignment_id

    @cached_property
    def driver(self):
        """Returns a Selenium WebDriver instance of the type requested in the
        configuration."""
        from dallinger.config import get_config
        config = get_config()
        if not config.ready:
            config.load()
        driver_url = config.get('webdriver_url', None)
        driver_type = config.get('webdriver_type', 'phantomjs').lower()

        if driver_url:
            capabilities = {}
            if driver_type == 'firefox':
                capabilities = webdriver.DesiredCapabilities.FIREFOX
            elif driver_type == 'chrome':
                capabilities = webdriver.DesiredCapabilities.CHROME
            elif driver_type == 'phantomjs':
                capabilities = webdriver.DesiredCapabilities.PHANTOMJS
            else:
                raise ValueError(
                    'Unsupported remote webdriver_type: {}'.format(driver_type))
            driver = webdriver.Remote(
                desired_capabilities=capabilities,
                command_executor=driver_url
            )
        elif driver_type == 'phantomjs':
            driver = webdriver.PhantomJS()
        elif driver_type == 'firefox':
            driver = webdriver.Firefox()
        elif driver_type == 'chrome':
            driver = webdriver.Chrome()
        else:
            raise ValueError(
                'Unsupported webdriver_type: {}'.format(driver_type))
        driver.set_window_size(1024, 768)
        logger.info("Created {} webdriver.".format(driver_type))
        return driver

    def sign_up(self):
        """Accept HIT, give consent and start experiment."""
        try:
            self.driver.get(self.URL)
            logger.info("Loaded ad page.")
            begin = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, 'btn-primary')))
            begin.click()
            logger.info("Clicked begin experiment button.")
            WebDriverWait(self.driver, 10).until(
                lambda d: len(d.window_handles) == 2)
            self.driver.switch_to_window(self.driver.window_handles[-1])
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

    def complete_questionnaire(self):
        """Complete the standard debriefing form."""
        pass

    def sign_off(self):
        """Submit questionnaire and finish."""
        try:
            feedback = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.ID, 'submit-questionnaire')))
            self.complete_questionnaire()
            feedback.click()
            logger.info("Clicked submit questionnaire button.")
            self.driver.switch_to_window(self.driver.window_handles[0])
            self.driver.set_window_size(1024, 768)
            logger.info("Switched back to initial window.")
            return True
        except TimeoutException:
            logger.error("Error during experiment sign off.")
            return False

    def complete_experiment(self, status):
        url = self.driver.current_url
        p = urlparse(url)
        complete_url = '%s://%s/%s?uniqueId=%s'
        complete_url = complete_url % (p.scheme,
                                       p.netloc,
                                       status,
                                       self.unique_id)
        self.driver.get(complete_url)
        logger.info("Forced call to %s: %s" % (status, complete_url))

    def run_experiment(self):
        """Sign up, run the ``participate`` method, then sign off and close
        the driver."""
        try:
            self.sign_up()
            self.participate()
            if self.sign_off():
                self.complete_experiment('worker_complete')
            else:
                self.complete_experiment('worker_failed')
        finally:
            self.driver.quit()
