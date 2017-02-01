"""Bots."""

from selenium import webdriver


class Bot(object):

    """A bot."""

    def __init__(self, URL):
        self.URL = URL
        self.driver = webdriver.PhantomJS()

    def participate(self):
        """Participate in the experiment."""
        raise NotImplementedError
