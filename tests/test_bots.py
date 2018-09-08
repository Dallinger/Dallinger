import json
import mock
import pytest
from selenium import webdriver

from dallinger.config import get_config

config = get_config()


class TestBots(object):

    def test_create_bot(self):
        """Create a bot."""
        config.ready = True
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert bot

    @pytest.mark.skipif(not pytest.config.getvalue("phantomjs"),
                        reason="--phantomjs was not specified")
    def test_bot_using_phantomjs(self):
        """Create a bot."""
        config.ready = True
        config.extend({'webdriver_type': u'phantomjs'})
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.PhantomJS)

    @pytest.mark.skipif(not pytest.config.getvalue("firefox"),
                        reason="--firefox was not specified")
    def test_bot_using_firefox(self):
        """Create a bot."""
        return
        config.ready = True
        config.extend({'webdriver_type': u'firefox'})
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Firefox)

    @pytest.mark.skipif(not pytest.config.getvalue("chrome"),
                        reason="--chrome was not specified")
    def test_bot_using_chrome(self):
        """Create a bot."""
        return
        config.ready = True
        config.extend({'webdriver_type': u'chrome'})
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Chrome)

    @pytest.mark.skipif(not pytest.config.getvalue("webdriver"),
                        reason="--webdriver was not specified")
    @pytest.mark.skipif(not pytest.config.getvalue("phantomjs"),
                        reason="--phantomjs was not specified")
    def test_bot_using_webdriver_phantomjs(self):
        """Create a bot."""
        config.ready = True
        config.extend({
            'webdriver_type': u'phantomjs',
            'webdriver_url': pytest.config.getvalue("webdriver").decode("ascii")
        })
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Remote)
        assert bot.driver.capabilities['browserName'] == 'phantomjs'

    @pytest.mark.skipif(not pytest.config.getvalue("webdriver"),
                        reason="--webdriver was not specified")
    @pytest.mark.skipif(not pytest.config.getvalue("firefox"),
                        reason="--firefox was not specified")
    def test_bot_using_webdriver_firefox(self):
        """Create a bot."""
        config.ready = True
        config.extend({
            'webdriver_type': u'firefox',
            'webdriver_url': pytest.config.getvalue("webdriver").decode("ascii")
        })
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Remote)
        assert bot.driver.capabilities['browserName'] == 'firefox'

    @pytest.mark.skipif(not pytest.config.getvalue("webdriver"),
                        reason="--webdriver was not specified")
    @pytest.mark.skipif(not pytest.config.getvalue("chrome"),
                        reason="--chrome was not specified")
    def test_bot_using_webdriver_chrome(self):
        """Create a bot."""
        config.ready = True
        config.extend({
            'webdriver_type': u'chrome',
            'webdriver_url': pytest.config.getvalue("webdriver").decode("ascii")
        })
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, webdriver.Remote)
        assert bot.driver.capabilities['browserName'] == 'chrome'


class TestHighPerformanceBot(object):

    @pytest.fixture
    def bot(self):
        config.ready = True
        from dallinger.bots import HighPerformanceBotBase
        bot = HighPerformanceBotBase(
            'https://dallinger.io/ad?assignment_id=assignment1&'
            'worker_id=worker1&participant_id=1&'
            'hit_id=hit1&recruiter=bogus'
        )
        # Override sleep and quorum subscribe for testing
        bot.stochastic_sleep = mock.Mock()
        bot.subscribe_to_quorum_channel = mock.Mock()
        return bot

    @pytest.fixture
    def req_post(self):
        with mock.patch('requests.post') as patch_post:
            yield patch_post

    @pytest.fixture
    def req_get(self):
        with mock.patch('requests.get') as patch_get:
            yield patch_get

    @pytest.fixture
    def fake_uuid(self):
        with mock.patch('uuid.uuid4') as patch_uuid4:
            patch_uuid4.hex.return_value = 'fakehash'
            yield patch_uuid4

    def test_create_bot(self, bot):
        """Create a bot."""
        from dallinger.bots import HighPerformanceBotBase
        assert isinstance(bot, HighPerformanceBotBase)
        assert bot.assignment_id == 'assignment1'
        assert bot.participant_id == '1'
        assert bot.hit_id == 'hit1'
        assert bot.worker_id == 'worker1'
        assert bot.unique_id == 'worker1:assignment1'

    def test_host(self, bot):
        assert bot.host == 'https://dallinger.io'

    def test_sign_up(self, bot, req_post, fake_uuid):
        mock_return = mock.Mock()
        mock_return.json.return_value = {
            "status": "OK",
            "participant": {"id": 4}
        }
        req_post.return_value = mock_return

        bot.sign_up()
        assert bot.subscribe_to_quorum_channel.called_once_with()
        assert req_post.called_once_with(
            'https://dallinger.io/participant/worker1/hit1/assignment1/debug?'
            'fingerprint_hash=fakehash&recruiter=bot:HighPerformanceBotBase'
        )
        assert bot.participant_id == 4

    def test_sign_off(self, bot, req_post):
        value = bot.sign_off()
        assert req_post.called_once_with(
            'https://dallinger.io/question/participant1',
            data={
                'question': 'questionnaire',
                'number': 1,
                'response': json.dumps({"engagement": 4, "difficulty": 3}),
            }
        )
        assert value is True

    def test_complete_experiment(self, bot, req_get):
        mock_return = mock.Mock()
        mock_return.dummy = 1
        req_get.return_value = mock_return

        response = bot.complete_experiment('worker_complete')
        assert req_get.called_once_with(
            'https://dallinger.io/worker_complete?participant_id=1'
        )
        # returns the response object
        assert response.dummy == 1
