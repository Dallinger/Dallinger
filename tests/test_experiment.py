import pytest
from dallinger.recruiters import CLIRecruiter
from dallinger.recruiters import HotAirRecruiter
from dallinger.recruiters import BotRecruiter


@pytest.mark.usefixtures('active_config')
class TestExperimentBaseClass(object):

    @pytest.fixture
    def exp(self):
        from dallinger.experiment import Experiment
        return Experiment()

    def test_recruiter_consults_recruiter_config_value(self, exp, active_config):
        active_config.extend({'recruiter': u'CLIRecruiter'})
        assert isinstance(exp.recruiter(), CLIRecruiter)

    def test_recruiter_for_debug_mode_no_bots(self, exp, active_config):
        active_config.extend({'mode': u'debug'})
        assert isinstance(exp.recruiter(), HotAirRecruiter)

    def test_recruiter_gets_bot_recruiter_by_nickname(self, exp, active_config):
        active_config.extend({'recruiter': u'bots'})
        assert exp.recruiter == BotRecruiter
