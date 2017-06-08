"""Test python experiment API"""
from uuid import UUID


class TestAPI(object):

    def test_uuid(self):
        from dallinger.experiment import Experiment
        exp_uuid = Experiment.make_uuid()
        assert isinstance(UUID(exp_uuid, version=4), UUID)

    def test_uuid_instance(self):
        from dallinger.experiment import Experiment
        exp = Experiment()
        exp_uuid = exp.make_uuid()
        assert isinstance(UUID(exp_uuid, version=4), UUID)
