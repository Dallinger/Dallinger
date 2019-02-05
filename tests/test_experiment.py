import pytest
import mock


def is_uuid(thing):
    return len(thing) == 36


@pytest.mark.usefixtures("active_config")
class TestExperimentBaseClass(object):
    @pytest.fixture
    def klass(self):
        from dallinger.experiment import Experiment

        return Experiment

    @pytest.fixture
    def exp(self, klass):
        return klass()

    def test_recruiter_delegates(self, exp, active_config):
        with mock.patch("dallinger.experiment.recruiters") as mock_module:
            exp.recruiter
            mock_module.from_config.assert_called_once_with(active_config)

    def test_make_uuid_generates_random_id_if_passed_none(self, klass):
        assert is_uuid(klass.make_uuid(None))

    def test_make_uuid_generates_random_id_if_passed_nonuuid(self, klass):
        assert is_uuid(klass.make_uuid("None"))

    def test_make_uuid_echos_a_valid_uuid(self, klass):
        valid = "8a61fc2e-43ae-cc13-fd1e-aa8f676096cc"
        assert klass.make_uuid(valid) == valid

    def test_quorum_zero_by_default(self, exp):
        assert exp.quorum == 0

    def test_not_overrecruited_with_default_zero_quorum(self, exp):
        assert not exp.is_overrecruited(waiting_count=1)

    def test_is_overrecruited_if_waiting_exceeds_quorum(self, exp):
        exp.quorum = 1
        assert exp.is_overrecruited(waiting_count=2)

    def test_not_overrecruited_if_waiting_equal_to_quorum(self, exp):
        exp.quorum = 1
        assert not exp.is_overrecruited(waiting_count=1)
