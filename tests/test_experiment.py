import pytest
from dallinger.recruiters import CLIRecruiter
from dallinger.recruiters import HotAirRecruiter
from dallinger.recruiters import MTurkRecruiter


@pytest.mark.usefixtures('active_config')
class TestExperimentBaseClass(object):

    @pytest.fixture
    def exp(self):
        from dallinger.experiment import Experiment
        return Experiment()

    def test_recruiter_consults_recruiter_config_value(self, exp, active_config):
        active_config.extend({'recruiter': u'CLIRecruiter'})
        assert isinstance(exp.recruiter, CLIRecruiter)

    def test_recruiter_for_debug_mode(self, exp, active_config):
        assert isinstance(exp.recruiter, HotAirRecruiter)

    def test_recruiter_name_trumps_debug_mode(self, exp, active_config):
        active_config.extend({'recruiter': u'CLIRecruiter'})
        assert isinstance(exp.recruiter, CLIRecruiter)

    def test_recruiter_gets_mturk_recruiter_by_default(self, exp, active_config):
        active_config.extend({'mode': u'sandbox'})
        assert isinstance(exp.recruiter, MTurkRecruiter)

    def test_unknown_recruiter_name_raises(self, exp, active_config):
        active_config.extend({'recruiter': u'bogus'})
        with pytest.raises(NotImplementedError):
            exp.recruiter
