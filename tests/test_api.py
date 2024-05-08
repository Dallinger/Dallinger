"""Test python experiment API"""

import random
from unittest import mock
from uuid import UUID

import pytest

import dallinger


@pytest.fixture
def exp():
    from dallinger.experiment import Experiment

    return Experiment()


class TestAPI(object):
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


class TestDataCollection(object):
    def test_collect_from_existing_local_file(self, exp, experiment_dir):
        existing_local_data_uid = "12345678-1234-5678-1234-567812345678"
        data = exp.collect(existing_local_data_uid)
        assert isinstance(data, dallinger.data.Data)

    def test_registered_uuid_will_not_allow_new_data_collection(self, exp):
        exp_uuid = "ed9e7ddd-3e97-452d-9e34-fee5d432258e"
        with mock.patch("dallinger.experiment.is_registered") as is_registered:
            is_registered.return_value = True
            with pytest.raises(RuntimeError):
                exp.collect(exp_uuid, recruiter="bots")

    def test_unregistered_uuid_will_not_allow_new_data_collection_in_debug(self, exp):
        unknown_uuid = "c85d5086-2fa7-4baf-9103-e142b9170cca"
        with mock.patch("dallinger.experiment.is_registered") as is_registered:
            is_registered.return_value = False
            with pytest.raises(RuntimeError):
                exp.collect(unknown_uuid, mode="debug", recruiter="bots")

    def test_collect_requires_valid_uuid(self, exp):
        existing_uuid = "totally-bogus-id"
        with mock.patch("dallinger.experiment.is_registered") as is_registered:
            is_registered.return_value = False
            with pytest.raises(ValueError):
                exp.collect(existing_uuid, recruiter="bots")
