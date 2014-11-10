from wallace import db
import os


class TestRecruiters(object):

    def setup(self):
        self.db = db.init_db(drop_all=True)
        os.chdir(os.path.join("examples", "bartlett1932"))

    def teardown(self):
        self.db.rollback()
        self.db.close()
        os.chdir("..")
        os.chdir("..")

    def add(self, *args):
        self.db.add_all(args)
        self.db.commit()

    def test_recruiter_generic(self):
        from wallace.recruiters import Recruiter
        assert Recruiter()

    def test_recruiter_psiturk(self):
        from wallace.recruiters import PsiTurkRecruiter
        assert PsiTurkRecruiter()

    def test_recruiter_simulated(self):
        from wallace.recruiters import SimulatedRecruiter
        assert SimulatedRecruiter()
