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


class TestMTurkRecruiter(object):

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

    def test_instantiation(self):
        from dallinger.recruiters import MTurkRecruiter
        recruiter = MTurkRecruiter()
        assert recruiter is not None

    def test_open_recruitment(self):
        from dallinger.recruiters import MTurkRecruiter
        recruiter = MTurkRecruiter()
        hit_info = recruiter.open_recruitment(n=1)
        assert 'hit_id' in hit_info
