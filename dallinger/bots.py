"""Bots."""

import json
import logging
import random
import uuid

import gevent
import requests
from cached_property import cached_property
from requests.exceptions import RequestException
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from six.moves import urllib

logger = logging.getLogger(__name__)

DRIVER_MAP = {
    "firefox": webdriver.Firefox,
    "chrome": webdriver.Chrome,
    "chrome_headless": webdriver.Chrome,
}
CAPABILITY_MAP = {
    "firefox": webdriver.DesiredCapabilities.FIREFOX,
    "chrome": webdriver.DesiredCapabilities.CHROME,
    "chrome_headless": webdriver.DesiredCapabilities.CHROME,
}


class BotBase(object):
    """A base class for bots that works with the built-in demos.

    This kind of bot uses Selenium to interact with the experiment
    using a real browser.
    """

    def __init__(
        self, URL, assignment_id="", worker_id="", participant_id="", hit_id=""
    ):
        if not URL:
            return
        logger.info("Creating bot with URL: %s." % URL)
        self.URL = URL

        parts = urllib.parse.urlparse(URL)
        query = urllib.parse.parse_qs(parts.query)

        if not assignment_id:
            # Dallinger experiments are not always consistent in whether the participant recruitment URL
            # uses snake_case or camelCase. This code accepts either format.
            assignment_id = self.get_from_query(
                query, ["assignment_id", "assignmentId"]
            )

        if not participant_id:
            participant_id = self.get_from_query(
                query, ["participant_id", "participantId"]
            )

        if not worker_id:
            worker_id = self.get_from_query(query, ["worker_id", "workerId"])

        if not hit_id:
            hit_id = self.get_from_query(query, ["hit_id", "hitId"])

        self.assignment_id = assignment_id
        self.participant_id = participant_id
        self.worker_id = worker_id
        self.hit_id = hit_id

        self.unique_id = worker_id + ":" + assignment_id

    @staticmethod
    def get_from_query(query, args):
        for arg in args:
            try:
                return query[arg][0]
            except KeyError:
                pass

        return ""

    def log(self, msg):
        logger.info("{}: {}".format(self.participant_id, msg))

    @cached_property
    def driver(self):
        """Returns a Selenium WebDriver instance of the type requested in the
        configuration."""
        from dallinger.config import get_config

        config = get_config()
        if not config.ready:
            config.load()
        driver_url = config.get("webdriver_url", None)
        driver_type = config.get("webdriver_type")
        driver = None

        if driver_url:
            capabilities = CAPABILITY_MAP.get(driver_type.lower())
            if capabilities is None:
                raise ValueError(
                    "Unsupported remote webdriver_type: {}".format(driver_type)
                )
            driver = webdriver.Remote(
                desired_capabilities=capabilities, command_executor=driver_url
            )
        else:
            driver_class = DRIVER_MAP.get(driver_type.lower())
            if driver_class is not None:
                kwargs = {}
                if driver_type.lower() == "chrome_headless":
                    from selenium.webdriver.chrome.options import Options

                    chrome_options = Options()
                    chrome_options.add_argument("--headless")
                    kwargs = {"options": chrome_options}
                driver = driver_class(**kwargs)

        if driver is None:
            raise ValueError("Unsupported webdriver_type: {}".format(driver_type))

        driver.set_window_size(1024, 768)
        logger.info("Created {} webdriver.".format(driver_type))
        return driver

    def sign_up(self):
        """Accept HIT, give consent and start experiment.

        This uses Selenium to click through buttons on the ad,
        consent, and instruction pages.
        """
        try:
            self.driver.get(self.URL)
            logger.info("Loaded ad page.")
            begin = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, "button.btn-primary, button.btn-success")
                )
            )
            begin.click()
            logger.info("Clicked begin experiment button.")
            WebDriverWait(self.driver, 10).until(lambda d: len(d.window_handles) == 2)
            self.driver.switch_to.window(self.driver.window_handles[-1])
            self.driver.set_window_size(1024, 768)
            logger.info("Switched to experiment popup.")
            consent = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.ID, "consent"))
            )
            consent.click()
            logger.info("Clicked consent button.")
            participate = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.CLASS_NAME, "btn-success"))
            )
            participate.click()
            logger.info("Clicked start button.")
            return True
        except TimeoutException:
            logger.error("Error during experiment sign up.")
            return False

    def participate(self):
        """Participate in the experiment.

        This method must be implemented by subclasses of ``BotBase``.
        """
        logger.error("Bot class does not define participate method.")
        raise NotImplementedError

    def complete_questionnaire(self):
        """Complete the standard debriefing form.

        Answers the questions in the base questionnaire.
        """
        logger.info("Complete questionnaire.")
        difficulty = self.driver.find_element("id", "difficulty")
        difficulty.value = "4"
        engagement = self.driver.find_element("id", "engagement")
        engagement.value = "3"

    def sign_off(self):
        """Submit questionnaire and finish.

        This uses Selenium to click the submit button on the questionnaire
        and return to the original window.
        """
        try:
            logger.info("Bot player signing off.")
            feedback = WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.ID, "submit-questionnaire"))
            )
            self.complete_questionnaire()
            feedback.click()
            logger.info("Clicked submit questionnaire button.")
            self.driver.switch_to.window(self.driver.window_handles[0])
            self.driver.set_window_size(1024, 768)
            logger.info("Switched back to initial window.")
            return True
        except TimeoutException:
            logger.error("Error during experiment sign off.")
            return False

    def complete_experiment(self, status):
        """Sends worker status ('worker_complete' or 'worker_failed')
        to the experiment server.
        """
        url = self.driver.current_url
        p = urllib.parse.urlparse(url)
        complete_url = "%s://%s/%s?participant_id=%s"
        complete_url = complete_url % (p.scheme, p.netloc, status, self.participant_id)
        self.driver.get(complete_url)
        logger.info("Forced call to %s: %s" % (status, complete_url))

    def run_experiment(self):
        """Sign up, run the ``participate`` method, then sign off and close
        the driver."""
        try:
            self.sign_up()
            self.participate()
            if self.sign_off():
                self.complete_experiment("worker_complete")
            else:
                self.complete_experiment("worker_failed")
        finally:
            self.driver.quit()


class HighPerformanceBotBase(BotBase):
    """A base class for bots that do not interact using a real browser.

    Instead, this kind of bot makes requests directly to the experiment server.
    """

    @property
    def driver(self):
        raise NotImplementedError

    @property
    def host(self):
        parsed = urllib.parse.urlparse(self.URL)
        return urllib.parse.urlunparse([parsed.scheme, parsed.netloc, "", "", "", ""])

    def run_experiment(self):
        """Runs the phases of interacting with the experiment
        including signup, participation, signoff, and recording completion.
        """
        self.sign_up()
        self.participate()
        if self.sign_off():
            self.complete_experiment("worker_complete")
        else:
            self.complete_experiment("worker_failed")

    def sign_up(self):
        """Signs up a participant for the experiment.

        This is done using a POST request to the /participant/ endpoint.
        """
        self.log("Bot player signing up.")
        self.subscribe_to_quorum_channel()
        while True:
            url = (
                "{host}/participant/{self.worker_id}/"
                "{self.hit_id}/{self.assignment_id}/"
                "debug?fingerprint_hash={hash}&recruiter=bots:{bot_name}".format(
                    host=self.host,
                    self=self,
                    hash=uuid.uuid4().hex,
                    bot_name=self.__class__.__name__,
                )
            )
            try:
                result = requests.post(url)
                result.raise_for_status()
            except RequestException:
                self.stochastic_sleep()
                continue

            if result.json()["status"] == "error":
                self.stochastic_sleep()
                continue

            self.on_signup(result.json())
            return True

    def sign_off(self):
        """Submit questionnaire and finish.

        This is done using a POST request to the /question/ endpoint.
        """
        self.log("Bot player signing off.")
        return self.complete_questionnaire()

    def complete_experiment(self, status):
        """Record worker completion status to the experiment server.

        This is done using a GET request to the /worker_complete
        or /worker_failed endpoints.
        """
        self.log("Bot player completing experiment. Status: {}".format(status))
        while True:
            url = "{host}/{status}?participant_id={participant_id}".format(
                host=self.host, participant_id=self.participant_id, status=status
            )
            try:
                result = requests.get(url)
                result.raise_for_status()
            except RequestException:
                self.stochastic_sleep()
                continue
            return result

    def stochastic_sleep(self):
        delay = max(1.0 / random.expovariate(0.5), 10.0)
        gevent.sleep(delay)

    def subscribe_to_quorum_channel(self):
        """In case the experiment enforces a quorum, listen for notifications
        before creating Partipant objects.
        """
        from dallinger.experiment_server.sockets import chat_backend

        self.log("Bot subscribing to quorum channel.")
        chat_backend.subscribe(self, "quorum")

    def on_signup(self, data):
        """Take any needed action on response from /participant call."""
        self.participant_id = data["participant"]["id"]

    @property
    def question_responses(self):
        return {"engagement": 4, "difficulty": 3}

    def complete_questionnaire(self):
        """Complete the standard debriefing form.

        Answers the questions in the base questionnaire.
        """
        while True:
            data = {
                "question": "questionnaire",
                "number": 1,
                "response": json.dumps(self.question_responses),
            }
            url = "{host}/question/{self.participant_id}".format(
                host=self.host, self=self
            )
            try:
                result = requests.post(url, data=data)
                result.raise_for_status()
            except RequestException:
                self.stochastic_sleep()
                continue
            return True
