import mock
import os
from dallinger import db
from dallinger.config import get_config


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
        'browser_exclude_rule': ['fakebrowser1', 'fakebrowser2'],
        'organization_name': 'fake org name',
        'notification_url': 'https://url-of-notification-route',
        'ad_group': 'fake ad group',
        'approve_requirement': 95,
        'us_only': True,
        'lifetime': 0.1,
        'title': 'fake experiment title',
        'description': 'fake HIT description',
        'keywords': ['kw1', 'kw2', 'kw3'],
    }
    defaults.update(kwargs)

    return defaults


class TestMTurkRecruiterAssumesConfigFileInCWD(object):

    def setup(self):
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
        from dallinger.mturk import MTurkService
        from dallinger.recruiters import MTurkRecruiter
        mockservice = mock.create_autospec(MTurkService)
        r = MTurkRecruiter(stub_config(**kwargs), 'http://fake-domain/ad')
        r.mturkservice = mockservice('fake key', 'fake secret')
        r.mturkservice.check_credentials.return_value = True
        return r

    def test_config_passed_to_constructor(self):
        recruiter = self.make_one()
        assert recruiter.config.get('title') == 'fake experiment title'

    def test_open_recruitment_check_creds_before_calling_create_hit(self):
        recruiter = self.make_one()
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.check_credentials.assert_called_once()

    def test_open_recruitment_single_recruitee(self):
        recruiter = self.make_one()
        recruiter.open_recruitment(n=1)
        recruiter.mturkservice.create_hit.assert_called_once_with(
            ad_url='http://fake-domain/ad',
            approve_requirement=95,
            description='fake HIT description',
            duration_hours=1.0,
            keywords=['kw1', 'kw2', 'kw3'],
            lifetime_days=0.1,
            max_assignments=1,
            notification_url='https://url-of-notification-route',
            reward=0.01,
            title='fake experiment title',
            us_only=True
        )
