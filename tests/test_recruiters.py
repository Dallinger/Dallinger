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

    def test_add_message_to_psiturk_recruiter_queue(self):
        from wallace.recruiters import PsiTurkRecruiter
        import boto.sqs

        recruiter = PsiTurkRecruiter()

        m = boto.sqs.message.Message()
        m.set_body("hello world.")
        recruiter.queue.write(m)

        rs = recruiter.queue.get_messages()
        for m in rs:
            assert m.get_body() == "hello world."

    def test_recruiter_simulated(self):
        from wallace.recruiters import SimulatedRecruiter
        assert SimulatedRecruiter()
