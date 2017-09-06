import pytest
import mock


@pytest.mark.usefixtures('active_config')
class TestExperimentBaseClass(object):

    @pytest.fixture
    def exp(self):
        from dallinger.experiment import Experiment
        return Experiment()

    def test_recruiter_delegates(self, exp, active_config):
        with mock.patch('dallinger.experiment.recruiters') as mock_module:
            exp.recruiter
            mock_module.from_config.assert_called_once_with(active_config)
