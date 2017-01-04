from dallinger import db
import os


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

    def test_open_recruitment(self):
        recruiter = self.make_one(**creds_from_environment())
        hit_info = recruiter.open_recruitment(n=1)
        assert 'hit_id' in hit_info
