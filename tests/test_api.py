"""Test python experiment API"""
import random
from uuid import UUID

import pytest

import dallinger


@pytest.mark.slow
class TestAPI(object):
    @pytest.fixture
    def exp(self):
        from dallinger.experiment import Experiment

        return Experiment()

    @pytest.fixture
    def bartlett(self):
        from dallinger.experiments import Bartlett1932

        return Bartlett1932()

    def test_uuid(self):
        from dallinger.experiment import Experiment

        exp_uuid = Experiment.make_uuid()
        assert isinstance(UUID(exp_uuid, version=4), UUID)

    def test_uuid_instance(self, exp):
        exp_uuid = exp.make_uuid()
        assert isinstance(UUID(exp_uuid, version=4), UUID)

    def test_uuid_reproducibility(self, exp):
        random.seed(1)
        exp_uuid1 = exp.make_uuid()
        exp_uuid2 = exp.make_uuid()
        random.seed(1)
        exp_uuid3 = exp.make_uuid()

        assert exp_uuid1 != exp_uuid2
        assert exp_uuid1 == exp_uuid3

    def test_collect_from_existing_s3_bucket(self, exp):
        exp = exp
        existing_s3_uuid = "12345-12345-12345-12345"
        data = exp.collect(existing_s3_uuid)
        assert isinstance(data, dallinger.data.Data)

    def test_registered_uuid_will_not_allow_new_data_collection(self, exp):
        dataless_uuid = "ed9e7ddd-3e97-452d-9e34-fee5d432258e"
        dallinger.data.register(dataless_uuid, "https://bogus-url.com/something")

        with pytest.raises(RuntimeError):
            exp.collect(dataless_uuid, recruiter="bots")

    def test_unregistered_uuid_will_not_allow_new_data_collection_in_debug(self, exp):
        unknown_uuid = "c85d5086-2fa7-4baf-9103-e142b9170cca"
        with pytest.raises(RuntimeError):
            exp.collect(unknown_uuid, mode="debug", recruiter="bots")

    def test_collect_requires_valid_uuid(self, exp):
        existing_uuid = "totally-bogus-id"
        with pytest.raises(ValueError):
            exp.collect(existing_uuid, recruiter="bots")
