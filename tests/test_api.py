"""Test python experiment API"""
import random
from uuid import UUID

import pytest

import dallinger


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

    def test_uuid_reproducibility(self):
        from dallinger.experiment import Experiment
        exp = Experiment()
        random.seed(1)
        exp_uuid1 = exp.make_uuid()
        exp_uuid2 = exp.make_uuid()
        random.seed(1)
        exp_uuid3 = exp.make_uuid()

        assert exp_uuid1 != exp_uuid2
        assert exp_uuid1 == exp_uuid3

    def test_collect(self):
        from dallinger.experiments import Bartlett1932
        exp = Bartlett1932()
        existing_uuid = "12345-12345-12345-12345"
        data = exp.collect(existing_uuid, recruiter=u'bots')
        assert isinstance(data, dallinger.data.Data)

        dataless_uuid = "ed9e7ddd-3e97-452d-9e34-fee5d432258e"
        dallinger.data.register(dataless_uuid, 'https://bogus-url.com/something')

        try:
            data = exp.collect(dataless_uuid, recruiter=u'bots')
        except RuntimeError:
            # This is expected for an already registered UUID with no accessible data
            pass
        else:
            pytest.fail('Did not raise RuntimeError for existing UUID')

        # In debug mode an unknown UUID fails
        unknown_uuid = "c85d5086-2fa7-4baf-9103-e142b9170cca"
        with pytest.raises(RuntimeError):
            data = exp.collect(unknown_uuid, mode=u'debug', recruiter=u'bots')

    def test_collect_requires_valid_uuid(self):
        from dallinger.experiments import Bartlett1932
        exp = Bartlett1932()
        existing_uuid = "totally-bogus-id"
        with pytest.raises(ValueError):
            exp.collect(existing_uuid, recruiter=u'bots')
