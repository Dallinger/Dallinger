from dallinger import db
import datetime
import os
from boto.mturk.price import Price


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
        'aws_region': 'fake region',
        'is_sandbox': True,
        'base_payment': 0.01,
        'duration': 1.0,
        'server': '0.0.0.0',
        'browser_exclude_rule': 'fakebrowser1, fakebrowser2',
        'organization_name': 'fake org name',
        'experiment_name': 'fake expermiment name',
        'notification_url': 'fake notification url',
        'contact_email_on_error': 'fake@fake.com',
        'ad_group': 'fake ad group',
        'approve_requirement': 'no idea what this is',
        'us_only': True,
        'lifetime': 1.0,
        'description': 'fake HIT description',
        'keywords': 'kw1, kw2, kw3'
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
        # XXX Ugh.
        self.db = db.init_db(drop_all=True)
        os.chdir(os.path.join("demos", "bartlett1932"))

    def teardown(self):
        # XXX Ugh.
        self.db.rollback()
        self.db.close()
        os.chdir("..")
        os.chdir("..")

    def test_instantiation_from_current_config(self):
        from dallinger.recruiters import MTurkRecruiter
        recruiter = MTurkRecruiter.from_current_config()
        assert recruiter.aws_region == 'us-east-1'


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
        config = stub_config()
        assert recruiter.aws_region == config.get('aws_region')

    def test_check_aws_credentials_good_credentials(self):
        recruiter = self.make_one(**creds_from_environment())
        is_authenticated = recruiter.check_aws_credentials()
        assert is_authenticated

    def test_check_aws_credentials_bad_credentials(self):
        recruiter = self.make_one()
        is_authenticated = recruiter.check_aws_credentials()
        assert not is_authenticated

    def test_check_aws_credentials_no_creds_set_raises(self):
        from dallinger.recruiters import MTurkRecruiterException
        empty_creds = {
            'aws_access_key_id': '',
            'aws_secret_access_key': ''
        }
        recruiter = self.make_one(**empty_creds)
        try:
            recruiter.check_aws_credentials()
        except MTurkRecruiterException:
            pass
        else:
            assert False

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
