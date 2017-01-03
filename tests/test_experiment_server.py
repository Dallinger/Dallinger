import os
import unittest


class FlaskAppTest(unittest.TestCase):
    """Base test case class for tests of the flask app."""

    def setUp(self, case=None):
        # The flask app assumes it is imported
        # while in an experiment directory.
        # `tests/experiment` mimics the files that are put
        # in place by dallinger.command_line.setup_experiment
        # when running via the CLI
        os.chdir('tests/experiment')

        from dallinger.experiment_server.experiment_server import app
        app.config['DEBUG'] = True
        app.config['TESTING'] = True
        self.app = app.test_client()

        import dallinger.db
        self.db = dallinger.db.init_db()

    def tearDown(self):
        self.db.rollback()
        self.db.close()
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

    def test_ad_no_params(self):
        resp = self.app.get('/ad')
        assert resp.status_code == 500
        assert 'Psychology Experiment - Error' in resp.data

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
