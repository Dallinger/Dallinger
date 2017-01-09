import os
from pytest import raises


def creds_from_environment():
    creds = {
        'aws_access_key_id': os.getenv('aws_access_key_id'),
        'aws_secret_access_key': os.getenv('aws_secret_access_key')
    }
    return creds


class TestMTurkService(object):

    def make_one(self, **kwargs):
        from dallinger.mturk import MTurkService
        return MTurkService(**kwargs)

    def test_check_credentials_good_credentials(self):
        service = self.make_one(**creds_from_environment())
        is_authenticated = service.check_credentials()

        assert is_authenticated

    def test_check_credentials_bad_credentials(self):
        from boto.mturk.connection import MTurkRequestError
        service = self.make_one(aws_access_key_id='bad', aws_secret_access_key='bad')
        with raises(MTurkRequestError):
            service.check_credentials()

    def test_check_credentials_no_creds_set_raises(self):
        from dallinger.mturk import MTurkServiceException
        empty_creds = {
            'aws_access_key_id': '',
            'aws_secret_access_key': ''
        }
        service = self.make_one(**empty_creds)

        with raises(MTurkServiceException):
            service.check_credentials()

    def test_register_hit_type(self):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw1'],
            'reward': .01,
            'duration': .25
        }
        service = self.make_one(**creds_from_environment())
        hit_type_id = service.register_hit_type(**config)

        assert isinstance(hit_type_id, unicode)

    def test_register_notification_url(self):
        config = {
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw1'],
            'reward': .01,
            'duration': .25
        }
        url = 'https://url-of-notification-route'
        service = self.make_one(**creds_from_environment())
        hit_type_id = service.register_hit_type(**config)

        assert service.set_rest_notification(url, hit_type_id) is True

    def test_create_hit(self):
        hit_config = {
            'ad_url': 'https://url-of-ad-route',
            'approve_requirement': 95,
            'us_only': True,
            'lifetime': 1.0,
            'max_assignments': 1,
            'notification_url': 'https://url-of-notification-route',
            'title': 'Test Title',
            'description': 'Test Description',
            'keywords': ['testkw1', 'testkw1'],
            'reward': .01,
            'duration': .25
        }
        service = self.make_one(**creds_from_environment())
        hit = service.create_hit(**hit_config)
        assert hit['status'] == 'Assignable'
