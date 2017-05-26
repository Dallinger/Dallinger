import json
import mock
import os
import pytest
import unittest
from datetime import datetime
from dallinger.config import get_config

config = get_config()
if not config.ready:
    config.load()


class FlaskAppTest(unittest.TestCase):
    """Base test case class for tests of the flask app."""

    experiment_dir = 'tests/experiment'

    def setUp(self, case=None):
        # The flask app assumes it is imported
        # while in an experiment directory.
        # `tests/experiment` mimics the files that are put
        # in place by dallinger.command_line.setup_experiment
        # when running via the CLI
        self.orig_dir = os.getcwd()
        os.chdir(self.experiment_dir)
        from dallinger.experiment_server import sockets
        app = sockets.app
        app.config['DEBUG'] = True
        app.config['TESTING'] = True
        self.app = app.test_client()

        import dallinger.db
        self.db = dallinger.db.init_db(drop_all=True)
        self.exp_config = config

    def tearDown(self):
        self.db.rollback()
        self.db.close()
        os.chdir(self.orig_dir)

        # Make sure the greenlet handling chat is stopped
        from dallinger.experiment_server.sockets import chat_backend
        chat_backend.stop()


class TestExperimentServer(FlaskAppTest):
    worker_counter = 0
    hit_counter = 0
    assignment_counter = 0

    def _create_participant(self):
        worker_id = self.worker_counter
        hit_id = self.hit_counter
        assignment_id = self.assignment_counter
        self.worker_counter += 1
        self.hit_counter += 1
        self.assignment_counter += 1
        resp = self.app.post('/participant/{}/{}/{}/debug'.format(
            worker_id, hit_id, assignment_id
        ))
        return json.loads(resp.data).get('participant', {}).get('id')

    def _create_node(self, participant_id):
        resp = self.app.post('/node/{}'.format(participant_id))
        return json.loads(resp.data)['node']['id']

    def _update_participant_status(self, participant_id, status):
        from dallinger.models import Participant
        participant = Participant.query.get(participant_id)
        participant.status = status

    def test_root(self):
        resp = self.app.get('/')
        assert resp.status_code == 404

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
        assert 'Please click the "Accept HIT" button on the Amazon site' not in resp.data
        assert 'Begin Experiment' in resp.data

    def test_ad_before_acceptance(self):
        resp = self.app.get('/ad', query_string={
            'hitId': 'debug',
            'assignmentId': 'ASSIGNMENT_ID_NOT_AVAILABLE',
            'mode': 'debug',
        })
        assert 'Please click the "Accept HIT" button on the Amazon site' in resp.data
        assert 'Begin Experiment' not in resp.data

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

    def test_participant_info(self):
        p_id = self._create_participant()
        resp = self.app.get('/participant/{}'.format(p_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('participant').get('status') == u'working'

    def test_prevent_duplicate_participant_for_worker(self):
        worker_id = self.worker_counter
        hit_id = self.hit_counter
        assignment_id = self.assignment_counter
        self.worker_counter += 1
        self.hit_counter += 1
        self.assignment_counter += 1
        resp = self.app.post('/participant/{}/{}/{}/debug'.format(
            worker_id, hit_id, assignment_id
        ))

        assert resp.status_code == 200

        resp = self.app.post('/participant/{}/{}/{}/debug'.format(
            worker_id, hit_id, assignment_id
        ))

        assert resp.status_code == 403

    def test_node_vectors(self):
        p_id = self._create_participant()
        n_id = self._create_node(p_id)
        resp = self.app.get('/node/{}/vectors'.format(n_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('vectors') == []

    def test_node_infos(self):
        p_id = self._create_participant()
        n_id = self._create_node(p_id)
        resp = self.app.get('/node/{}/infos'.format(n_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('infos') == []

    def test_summary(self):
        resp = self.app.get('/summary')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('completed') is False
        assert data.get('unfilled_networks') == 1
        assert data.get('required_nodes') == 2
        assert data.get('nodes_remaining') == 2
        assert data.get('summary') == []

        p1_id = self._create_participant()
        self._create_node(p1_id)
        resp = self.app.get('/summary')
        data = json.loads(resp.data)
        assert data.get('completed') is False
        assert data.get('nodes_remaining') == 1
        worker_summary = data.get('summary')
        assert len(worker_summary) == 1
        assert worker_summary[0] == [u'working', 1]

        p2_id = self._create_participant()
        self._create_node(p2_id)
        resp = self.app.get('/summary')
        data = json.loads(resp.data)
        assert data.get('completed') is False
        assert data.get('nodes_remaining') == 0
        worker_summary = data.get('summary')
        assert len(worker_summary) == 1
        assert worker_summary[0] == [u'working', 2]

        self._update_participant_status(p1_id, 'submitted')
        self._update_participant_status(p2_id, 'approved')

        resp = self.app.get('/summary')
        data = json.loads(resp.data)
        assert data.get('completed') is True
        worker_summary = data.get('summary')
        assert len(worker_summary) == 2
        assert worker_summary[0] == [u'approved', 1]
        assert worker_summary[1] == [u'submitted', 1]

    def test_existing_experiment_property(self):
        p_id = self._create_participant()
        resp = self.app.get('/experiment/exists'.format(p_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('exists') is True

    def test_nonexisting_experiment_property(self):
        p_id = self._create_participant()
        resp = self.app.get('/experiment/missing'.format(p_id))
        assert resp.status_code == 404

    def test_not_found(self):
        resp = self.app.get('/BOGUS')
        assert resp.status_code == 404

    def test_launch(self):
        resp = self.app.post('/launch', {})
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert 'recruitment_url' in data


@pytest.mark.xfail(reason="TestExperiment class mysteriously None when called via super()")
@pytest.mark.usefixtures('experiment_dir')
class TestWorkerFunctionIntegration(object):

    dispatcher = 'dallinger.experiment_server.experiment_server.WorkerEvent'

    @pytest.fixture
    def worker_func(self):
        from dallinger.config import get_config
        config = get_config()
        if not config.ready:
            config.load()
        from dallinger.experiment_server.experiment_server import worker_function
        yield worker_function

    def test_all_invalid_values(self, worker_func):
        worker_func('foo', 'bar', 'baz')

    def test_uses_assignment_id(self, worker_func, db_session):
        from dallinger.models import Participant
        participant = Participant(
            worker_id='1', hit_id='1', assignment_id='1', mode="test")
        db_session.add(participant)

        with mock.patch(self.dispatcher) as mock_baseclass:
            runner = mock.Mock()
            mock_baseclass.for_name = mock.Mock(return_value=runner)
            worker_func(
                event_type='MockEvent',
                assignment_id='1',
                participant_id=None
            )
            mock_baseclass.for_name.assert_called_once_with('MockEvent')
            runner.call_args[0][0] is participant

    def test_uses_participant_id(self, worker_func, db_session):
        from dallinger.models import Participant
        participant = Participant(
            worker_id='1', hit_id='1', assignment_id='1', mode="test")
        db_session.add(participant)
        db_session.commit()

        with mock.patch(self.dispatcher) as mock_baseclass:
            runner = mock.Mock()
            mock_baseclass.for_name = mock.Mock(return_value=runner)
            worker_func(
                event_type='MockEvent',
                assignment_id=None,
                participant_id=participant.id
            )
            mock_baseclass.for_name.assert_called_once_with('MockEvent')
            runner.call_args[0][0] is participant


class TestWorkerEvents(object):

    def test_dispatch(self):
        from dallinger.experiment_server.worker_events import WorkerEvent
        from dallinger.experiment_server.worker_events import AssignmentSubmitted
        cls = WorkerEvent.for_name('AssignmentSubmitted')

        assert cls is AssignmentSubmitted

    def test_dispatch_with_unsupported_event_type(self):
        from dallinger.experiment_server.worker_events import WorkerEvent
        assert WorkerEvent.for_name('nonsense') is None


end_time = datetime(2000, 01, 01)


@pytest.fixture
def experiment():
    from dallinger.experiment import Experiment
    experiment = mock.Mock(spec=Experiment)

    return experiment


@pytest.fixture
def standard_args(experiment):
    participant = mock.Mock(status="working")
    assignment_id = 'some assignment id'
    now = end_time
    session = mock.Mock()
    config = {}

    return {
        'participant': participant,
        'assignment_id': assignment_id,
        'experiment': experiment,
        'now': now,
        'session': session,
        'config': config,
        'now': now
    }.copy()


class TestAssignmentSubmitted(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import AssignmentSubmitted
        experiment = standard_args['experiment']
        experiment.attention_check = mock.Mock(return_value=True)
        experiment.data_check = mock.Mock(return_value=True)
        experiment.bonus = mock.Mock(return_value=0.0)
        experiment.bonus_reason = mock.Mock(return_value="You rock.")
        standard_args['config'] = {'base_payment': 1.00}
        return AssignmentSubmitted(**standard_args)

    def test_calls_reward_bonus_if_experiment_returns_bonus_more_than_one_cent(self, runner):
        runner.experiment.bonus.return_value = .02
        runner()
        runner.experiment.recruiter().reward_bonus.assert_called_once_with(
            'some assignment id',
            .02,
            "You rock."
        )

    def test_no_reward_bonus_if_experiment_returns_bonus_less_than_one_cent(self, runner):
        runner()
        runner.experiment.recruiter().reward_bonus.assert_not_called()
        assert "NOT paying bonus" in str(runner.experiment.log.call_args_list)

    def test_sets_participant_bonus_regardless(self, runner):
        runner.experiment.bonus.return_value = .005
        runner()
        assert runner.participant.bonus == .005

    def test_approve_hit_called_on_recruiter(self, runner):
        runner()
        runner.experiment.recruiter().approve_hit.assert_called_once_with(
            'some assignment id'
        )

    def test_participant_base_pay_set(self, runner):
        runner()
        assert runner.participant.base_pay == 1.0

    def test_participant_status_set(self, runner):
        runner()
        assert runner.participant.status == 'approved'

    def test_participant_end_time_set(self, runner):
        runner()
        assert runner.participant.end_time == end_time

    def test_submission_successful_called_on_experiment(self, runner):
        runner()
        runner.experiment.submission_successful.assert_called_once_with(
            participant=runner.participant
        )

    def test_recruit_called_on_experiment(self, runner):
        runner()
        runner.experiment.recruit.assert_called_once()

    def test_does_nothing_if_already_approved_worker(self, runner):
        runner.participant.status = 'approved'
        runner()
        runner.session.assert_not_called()

    def test_sets_participant_status_on_failed_data_check(self, runner):
        runner.experiment.data_check.return_value = False
        runner()
        assert runner.participant.status == 'bad_data'

    def test_calls_data_check_failed_on_failed_data_check(self, runner):
        runner.experiment.data_check.return_value = False
        runner()
        runner.experiment.data_check_failed.assert_called_once_with(
            participant=runner.participant
        )

    def test_recruits_another_on_failed_data_check(self, runner):
        runner.experiment.data_check.return_value = False
        runner()
        runner.experiment.recruiter().recruit_participants.assert_called_once_with(
            n=1
        )

    def test_no_bonus_inquiry_on_failed_data_check(self, runner):
        runner.experiment.data_check.return_value = False
        runner()
        runner.experiment.bonus.assert_not_called()

    def test_sets_participant_status_on_failed_attention_check(self, runner):
        runner.experiment.attention_check.return_value = False
        runner()
        assert runner.participant.status == 'did_not_attend'

    def test_calls_attention_check_failed_on_failed_attention_check(self, runner):
        runner.experiment.attention_check.return_value = False
        runner()
        runner.experiment.attention_check_failed.assert_called_once_with(
            participant=runner.participant
        )


class TestBotAssignmentSubmitted(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import BotAssignmentSubmitted
        return BotAssignmentSubmitted(**standard_args)

    def test_participant_status_set(self, runner):
        runner()
        assert runner.participant.status == 'approved'

    def test_participant_end_time_set(self, runner):
        runner()
        assert runner.participant.end_time == end_time

    def test_submission_successful_called_on_experiment(self, runner):
        runner()
        runner.experiment.submission_successful.assert_called_once_with(
            participant=runner.participant
        )

    def test_approve_hit_called_on_recruiter(self, runner):
        runner()
        runner.experiment.recruiter().approve_hit.assert_called_once_with(
            'some assignment id'
        )

    def test_recruit_called_on_experiment(self, runner):
        runner()
        runner.experiment.recruit.assert_called_once()


class TestBotAssignmentRejected(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import BotAssignmentRejected
        return BotAssignmentRejected(**standard_args)

    def test_sets_participant_status(self, runner):
        runner()
        assert runner.participant.status == 'rejected'

    def test_sets_participant_end_time(self, runner):
        runner()
        assert runner.participant.end_time == end_time

    def test_calls_recruit_on_experiment(self, runner):
        runner()
        runner.experiment.recruit.assert_called_once()


class TestAssignmentAccepted(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import AssignmentAccepted
        return AssignmentAccepted(**standard_args)

    def test_does_nothing_without_raising(self, runner):
        runner()


class TestAssignmentAbandoned(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import AssignmentAbandoned
        return AssignmentAbandoned(**standard_args)

    def test_is_noop_if_participant_not_working(self, runner):
        runner.participant.status = 'not working'
        runner()
        assert runner.participant.status == 'not working'

    def test_sets_participant_status(self, runner):
        runner()
        assert runner.participant.status == 'abandoned'

    def test_sets_participant_end_time(self, runner):
        runner()
        assert runner.participant.end_time == end_time

    def test_calls_assignment_abandoned_on_experiment(self, runner):
        runner()
        runner.experiment.assignment_abandoned.assert_called_once_with(
            participant=runner.participant
        )


class TestAssignmentReturned(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import AssignmentReturned
        return AssignmentReturned(**standard_args)

    def test_is_noop_if_participant_not_working(self, runner):
        runner.participant.status = 'not working'
        runner()
        assert runner.participant.status == 'not working'

    def test_sets_participant_status(self, runner):
        runner()
        assert runner.participant.status == 'returned'

    def test_sets_participant_end_time(self, runner):
        runner()
        assert runner.participant.end_time == end_time

    def test_calls_assignment_returned_on_experiment(self, runner):
        runner()
        runner.experiment.assignment_returned.assert_called_once_with(
            participant=runner.participant
        )


class TestAssignmentReassigned(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import AssignmentReassigned
        return AssignmentReassigned(**standard_args)

    def test_sets_participant_status(self, runner):
        runner()
        assert runner.participant.status == 'replaced'

    def test_sets_participant_end_time(self, runner):
        runner()
        assert runner.participant.end_time == end_time

    def test_calls_assignment_returned_on_experiment(self, runner):
        runner()
        runner.experiment.assignment_reassigned.assert_called_once_with(
            participant=runner.participant
        )


class TestNotificationMissing(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import NotificationMissing
        return NotificationMissing(**standard_args)

    def test_sets_participant_status_for_working_participant(self, runner):
        runner()
        assert runner.participant.status == 'missing_notification'

    def test_does_not_set_participant_status_for_participant_otherwise(self, runner):
        runner.participant.status = 'something other than "working"'
        runner()
        assert runner.participant.status == 'something other than "working"'

    def test_sets_participant_end_time_if_working(self, runner):
        runner()
        assert runner.participant.end_time == end_time

    def test_does_not_set_participant_end_time_for_participant_otherwise(self, runner):
        runner.participant.status = 'something other than "working"'
        marker = object()
        runner.participant.end_time = marker
        runner()
        assert runner.participant.end_time is marker
