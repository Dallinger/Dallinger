import mock
import pytest
from dallinger.recruiters import HotAirRecruiter
from dallinger.recruiters import BotRecruiter


class TestExperimentBaseClass(object):

    @pytest.fixture
    def exp(self):
        from dallinger.experiment import Experiment
        return Experiment()

    def test_recruiter_consults_recruiter_config_value(self, stub_config, exp):
        with mock.patch('dallinger.experiment.get_config') as mock_config:
            stub_config.extend({'recruiter': u'HotAirRecruiter'})
            mock_config.return_value = stub_config

            assert isinstance(exp.recruiter(), HotAirRecruiter)

    def test_recruiter_for_debug_mode_no_bots(self, stub_config, exp):
        with mock.patch('dallinger.experiment.get_config') as mock_config:
            stub_config.extend({'mode': u'debug'})
            mock_config.return_value = stub_config

            assert isinstance(exp.recruiter(), HotAirRecruiter)

    def test_recruiter_gets_bot_recruiter_by_nickname(self, stub_config, exp):
        with mock.patch('dallinger.experiment.get_config') as mock_config:
            stub_config.extend({'recruiter': u'bots'})
            mock_config.return_value = stub_config

            assert exp.recruiter == BotRecruiter.from_current_config
