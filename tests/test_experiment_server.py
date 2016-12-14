import os
import unittest


class FlaskAppTest(unittest.TestCase):

    def setUp(self, case=None):
        # psiturk's experiment module assumes it is imported
        # while in the experiment directory
        os.chdir('tests/experiment')

        from psiturk.experiment import app
        app.config['DEBUG'] = True
        app.config['TESTING'] = True
        self.app = app.test_client()

        import dallinger.db
        dallinger.db.init_db()

    def tearDown(self):
        os.chdir('../..')


class TestExperimentServer(FlaskAppTest):

    def test_default(self):
        resp = self.app.get('/')
        assert 'Welcome to Dallinger!' in resp.data

    def test_favicon(self):
        resp = self.app.get('/favicon.ico')
        assert resp.content_type == 'image/x-icon'
        assert resp.content_length > 0

    def test_robots(self):
        resp = self.app.get('/robots.txt')
        assert 'User-agent' in resp.data

    def test_ad(self):
        resp = self.app.get('/ad', query_string={
            'hitId': 'debug',
            'assignmentId': '1',
            'mode': 'debug',
        })
        assert 'Psychology Experiment' in resp.data

    def test_consent(self):
        resp = self.app.get('/consent', query_string={
            'hit_id': 'debug',
            'assignment_id': '1',
            'worker_id': '1',
            'mode': 'debug',
        })
        assert 'Informed Consent Form' in resp.data

    def test_not_found(self):
        resp = self.app.get('/BOGUS')
        assert resp.status_code == 404
