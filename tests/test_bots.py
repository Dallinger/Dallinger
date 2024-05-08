import json
from unittest import mock

import pytest
from selenium import webdriver


class TestBots(object):
    def test_create_bot(self, active_config):
        """Create a bot."""
        from dallinger.bots import BotBase

        bot = BotBase("http://dallinger.io")
        assert bot

    @pytest.mark.slow
    def test_bot_driver_default_is_chrome(self, active_config):
        from dallinger.bots import BotBase

        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Chrome)
        bot.driver.quit()

    @pytest.mark.slow
    def test_bot_using_chrome_headless(self, active_config):
        """Create a bot."""
        active_config.extend({"webdriver_type": "chrome_headless"})
        from dallinger.bots import BotBase

        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Chrome)
        bot.driver.quit()

    @pytest.mark.usefixtures("check_firefox")
    def test_bot_using_firefox(self, active_config):
        """Create a bot."""
        active_config.extend({"webdriver_type": "firefox"})
        from dallinger.bots import BotBase

        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Firefox)

    @pytest.mark.usefixtures("check_chrome")
    def test_bot_using_chrome(self, active_config):
        """Create a bot."""
        active_config.extend({"webdriver_type": "chrome"})
        from dallinger.bots import BotBase

        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Chrome)

    @pytest.mark.usefixtures("check_webdriver")
    @pytest.mark.usefixtures("check_chrome_headless")
    def test_bot_using_webdriver_chrome_headless(self, active_config):
        """Create a bot."""
        active_config.extend(
            {
                "webdriver_type": "chrome_headless",
                "webdriver_url": self._config.getvalue("webdriver").decode("ascii"),
            }
        )
        from dallinger.bots import BotBase

        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Remote)
        assert bot.driver.capabilities["browserName"] == "chrome"

    @pytest.mark.usefixtures("check_webdriver")
    @pytest.mark.usefixtures("check_firefox")
    def test_bot_using_webdriver_firefox(self, active_config):
        """Create a bot."""
        active_config.extend(
            {
                "webdriver_type": "firefox",
                "webdriver_url": self._config.getvalue("webdriver").decode("ascii"),
            }
        )
        from dallinger.bots import BotBase

        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Remote)
        assert bot.driver.capabilities["browserName"] == "firefox"

    @pytest.mark.usefixtures("check_webdriver")
    @pytest.mark.usefixtures("check_chrome")
    def test_bot_using_webdriver_chrome(self, active_config):
        """Create a bot."""
        active_config.extend(
            {
                "webdriver_type": "chrome",
                "webdriver_url": self._config.getvalue("webdriver").decode("ascii"),
            }
        )
        from dallinger.bots import BotBase

        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Remote)
        assert bot.driver.capabilities["browserName"] == "chrome"


class TestHighPerformanceBot(object):
    @pytest.fixture
    def bot(self, active_config):
        from dallinger.bots import HighPerformanceBotBase

        bot = HighPerformanceBotBase(
            "https://dallinger.io/ad?assignment_id=assignment1&"
            "worker_id=worker1&participant_id=1&"
            "hit_id=hit1&recruiter=bogus"
        )
        # Override sleep and quorum subscribe for testing
        bot.stochastic_sleep = mock.Mock()
        bot.subscribe_to_quorum_channel = mock.Mock()
        return bot

    @pytest.fixture
    def req_post(self):
        with mock.patch("requests.post") as patch_post:
            yield patch_post

    @pytest.fixture
    def req_get(self):
        with mock.patch("requests.get") as patch_get:
            yield patch_get

    @pytest.fixture
    def fake_uuid(self):
        with mock.patch("uuid.uuid4") as patch_uuid4:
            patch_uuid4.return_value.hex = "fakehash"
            yield patch_uuid4

    def test_create_bot(self, bot):
        """Create a bot."""
        from dallinger.bots import HighPerformanceBotBase

        assert isinstance(bot, HighPerformanceBotBase)
        assert bot.assignment_id == "assignment1"
        assert bot.participant_id == "1"
        assert bot.hit_id == "hit1"
        assert bot.worker_id == "worker1"
        assert bot.unique_id == "worker1:assignment1"

    def test_host(self, bot):
        assert bot.host == "https://dallinger.io"

    def test_sign_up(self, bot, req_post, fake_uuid):
        mock_return = mock.Mock()
        mock_return.json.return_value = {"status": "OK", "participant": {"id": 4}}
        req_post.return_value = mock_return

        bot.sign_up()
        bot.subscribe_to_quorum_channel.assert_called_once_with()
        req_post.assert_called_once_with(
            "https://dallinger.io/participant/worker1/hit1/assignment1/debug?"
            "fingerprint_hash=fakehash&recruiter=bots:HighPerformanceBotBase"
        )
        assert bot.participant_id == 4

    def test_sign_off(self, bot, req_post):
        value = bot.sign_off()
        req_post.assert_called_once_with(
            "https://dallinger.io/question/1",
            data={
                "question": "questionnaire",
                "number": 1,
                "response": json.dumps({"engagement": 4, "difficulty": 3}),
            },
        )
        assert value is True

    def test_complete_experiment(self, bot, req_get):
        mock_return = mock.Mock()
        mock_return.dummy = 1
        req_get.return_value = mock_return

        response = bot.complete_experiment("worker_complete")
        req_get.assert_called_once_with(
            "https://dallinger.io/worker_complete?participant_id=1"
        )
        # returns the response object
        assert response.dummy == 1
