import os

import pytest

from dallinger.pytest_dallinger import (
    wait_for_element,
    wait_for_text,
    wait_until_clickable,
)


@pytest.fixture(scope="class")
def bartlett_dir(root):
    os.chdir(os.path.join(os.path.dirname(__file__), "..", "dlgr/demos/bartlett1932"))
    yield
    os.chdir(root)


@pytest.mark.usefixtures("bartlett_dir")
class TestBartlett1932(object):
    """Tests for the Bartlett1932 demo class"""

    @pytest.fixture
    def bartlett_config(self, active_config):
        active_config.register_extra_parameters()
        active_config.set("num_participants", 3)
        yield active_config

    @pytest.fixture
    def demo(self, db_session, bartlett_config):
        from dlgr.demos.bartlett1932.experiment import Bartlett1932

        instance = Bartlett1932(db_session)
        yield instance

    @pytest.fixture
    def two_iterations(self):
        # Sets environment variable for debug sub-process configuration
        os.environ["NUM_PARTICIPANTS"] = "2"
        yield None
        del os.environ["NUM_PARTICIPANTS"]

    def test_networks_holds_single_experiment_node(self, demo):
        assert len(demo.networks()) == 1
        assert "experiment" == demo.networks()[0].role

    @pytest.mark.slow
    def test_bartlett_selenium(self, two_iterations, bot_recruits):
        for participant, bot in enumerate(bot_recruits):
            driver = bot.driver
            # Wait until story has loaded
            text_el = wait_for_text(driver, "story", "<< loading >>", removed=True)
            assert text_el.text
            text = text_el.text

            # If we are not the first participant, look for modified text
            # from prior participants
            if participant > 0:
                assert "Copy {} of:".format(participant) in text

            # Acknowledge having read the text
            button = wait_until_clickable(driver, "finish-reading")
            assert button.tag_name == "button"
            assert button.text == "I'm done reading."
            button.click()

            # Enter modified text and submit
            text_input = wait_for_element(driver, "reproduction")
            text_input.send_keys("Copy {} of: {}".format(participant + 1, text))

            submit = wait_until_clickable(driver, "submit-response")
            assert submit.tag_name == "button"
            assert submit.text == "Submit"
            submit.click()
