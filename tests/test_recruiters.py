import datetime
import os
from boto.mturk.price import Price
from dallinger import db
from dallinger.config import get_config
from nose.tools import assert_raises


class TestRecruiters(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)
        os.chdir(os.path.join("demos", "bartlett1932"))

    def teardown(self):
        self.db.rollback()
        self.db.close()
        os.chdir("..")
        os.chdir("..")

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_recruiter_generic(self):
        from dallinger.recruiters import Recruiter
        assert Recruiter()

    def test_recruiter_psiturk(self):
        from dallinger.recruiters import PsiTurkRecruiter
        assert PsiTurkRecruiter()

    def test_recruiter_simulated(self):
        from dallinger.recruiters import SimulatedRecruiter
        assert SimulatedRecruiter()


def stub_config(**kwargs):
    defaults = {
        'aws_access_key_id': 'fake key',
        'aws_secret_access_key': 'fake secret',
        'launch_in_sandbox_mode': True,
        'base_payment': 0.01,
        'duration': 1.0,
        'server': '0.0.0.0',
        'browser_exclude_rule': 'fakebrowser1, fakebrowser2',
        'organization_name': 'fake org name',
        'notification_url': 'fake notification url',
        'contact_email_on_error': 'fake@fake.com',
        'ad_group': 'fake ad group',
        'approve_requirement': 95,
        'us_only': True,
        'lifetime': 1.0,
        'title': 'fake experiment title',
        'description': 'fake HIT description',
        'keywords': 'kw1, kw2, kw3',
    }
    defaults.update(kwargs)

    return defaults


def creds_from_environment():
    creds = {
        'aws_access_key_id': os.getenv('aws_access_key_id'),
        'aws_secret_access_key': os.getenv('aws_secret_access_key')
    }
    return creds


class TestMTurkRecruiterAssumesConfigFileInCWD(object):

    def setup(self):
        config = get_config()
        config.ready = False
        self.db = db.init_db(drop_all=True)
        os.chdir(os.path.join("demos", "bartlett1932"))

    def teardown(self):
        self.db.rollback()
        self.db.close()
        os.chdir("..")
        os.chdir("..")

    def test_instantiation_from_current_config(self):
        from dallinger.recruiters import MTurkRecruiter
        recruiter = MTurkRecruiter.from_current_config()
        assert recruiter.config.get('title') == 'War of the Ghosts'


class TestMTurkRecruiter(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)

    def teardown(self):
        self.db.rollback()
        self.db.close()

    def make_one(self, **kwargs):
        from dallinger.recruiters import MTurkRecruiter
        config = stub_config(**kwargs)
        return MTurkRecruiter(config)

    def test_config_passed_to_constructor(self):
        recruiter = self.make_one()
        assert recruiter.config.get('title') == 'fake experiment title'

    def test_check_aws_credentials_good_credentials(self):
        recruiter = self.make_one(**creds_from_environment())
        is_authenticated = recruiter.check_aws_credentials()
        assert is_authenticated

    def test_check_aws_credentials_bad_credentials(self):
        from boto.mturk.connection import MTurkRequestError
        recruiter = self.make_one()
        with assert_raises(MTurkRequestError):
            recruiter.check_aws_credentials()

    def test_check_aws_credentials_no_creds_set_raises(self):
        from dallinger.recruiters import MTurkRecruiterException
        empty_creds = {
            'aws_access_key_id': '',
            'aws_secret_access_key': ''
        }
        recruiter = self.make_one(**empty_creds)

        with assert_raises(MTurkRecruiterException):
            recruiter.check_aws_credentials()

    def test_register_hit_type(self):
        config = {
            "title": 'Test Title',
            "description": 'Test Description',
            "keywords": ['testkw1', 'testkw1'],
            "reward": Price(.01),
            "duration": datetime.timedelta(hours=.25)
        }
        recruiter = self.make_one(**creds_from_environment())
        hit_type = recruiter.register_hit_type(config)
        assert hasattr(hit_type, 'HITTypeId')

    def test_register_notification_url(self):
        config = {
            "title": 'Test Title',
            "description": 'Test Description',
            "keywords": ['testkw1', 'testkw1'],
            "reward": Price(.01),
            "duration": datetime.timedelta(hours=.25)
        }
        url = 'https://url-of-real-ad-route'
        recruiter = self.make_one(**creds_from_environment())
        hit_type = recruiter.register_hit_type(config)

        result = recruiter.register_notification_url(url, hit_type.HITTypeId)

        assert 'NONSENSE' in result

    def test_create_hit(self):
        hit_config = {
            "ad_url": 'https://www.google.com/',  # ???
            "approve_requirement": 95,
            "us_only": True,
            "lifetime": datetime.timedelta(hours=1),
            "max_assignments": 1,
            "notification_url": 'fake notification url',
            "title": 'Test Title',
            "description": 'Test Description',
            "keywords": ['testkw1', 'testkw1'],
            "reward": Price(.01),
            "duration": datetime.timedelta(hours=.25)
        }
        recruiter = self.make_one(**creds_from_environment())
        hit = recruiter.create_hit(hit_config)
        assert 'hit_id' in hit

    # def test_open_recruitment(self):
    #     recruiter = self.make_one(**creds_from_environment())
    #     hit_info = recruiter.open_recruitment(n=1)
    #     assert 'hit_id' in hit_info
