
class TestBots(object):

    def test_create_bot(self):
        """Create a bot."""
        from dallinger.bots import Bot
        bot = Bot("http://dallinger.io")
        assert bot
