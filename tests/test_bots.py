
class TestBots(object):

    def test_create_bot(self):
        """Create a bot."""
        from dallinger.bots import BotBase
        bot = BotBase("http://dallinger.io")
        assert bot
