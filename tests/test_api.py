"""Test python experiment API"""
import dallinger
import pytest
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

    def test_retrieve(self):
        from dallinger.experiments import Bartlett1932
        exp = Bartlett1932()
        existing_uuid = "12345-12345-12345-12345"
        data = exp.retrieve(existing_uuid, recruiter=u'bots')
        assert isinstance(data, dallinger.data.Data)

        dataless_uuid = "55555-55555-55555-55555"
        dallinger.data.register(dataless_uuid, 'https://bogus-url.com/something')

        try:
            data = exp.retrieve(dataless_uuid, recruiter=u'bots')
        except RuntimeError:
            # This is expected for an already registered UUID with no accessible data
            pass
        else:
            pytest.fail('Did not raise RuntimeError for existing UUID')

        # In debug mode an unknown UUID fails
        unknown_uuid = "66666-66666-66666-66666"
        try:
            data = exp.retrieve(unknown_uuid, mode=u'debug', recruiter=u'bots')
        except RuntimeError:
            # This is expected for an already registered UUID with no accessible data
            pass
        else:
            pytest.fail('Did not raise RuntimeError for unknown debug UUID')
