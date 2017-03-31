import pytest
from selenium.webdriver import PhantomJS, Firefox, Remote

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
        assert isinstance(bot.driver, PhantomJS)

    @pytest.mark.skipif(not pytest.config.getvalue("firefox"),
                        reason="--firefox was not specified")
    def test_bot_using_firefox(self):
        """Create a bot."""
        return
        config.ready = True
        config.extend({'webdriver_type': u'firefox'})
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert isinstance(bot.driver, Firefox)

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
        assert isinstance(bot.driver, Remote)
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
        assert isinstance(bot.driver, Remote)
        assert bot.driver.capabilities['browserName'] == 'firefox'
