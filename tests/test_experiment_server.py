import json
import mock
import pytest
from datetime import datetime


@pytest.mark.usefixtures('experiment_dir', 'active_config', 'db_session')
class TestWorkerComplete(object):

    def test_with_no_participant_id_returns_error(self, webapp):
        resp = webapp.get('/worker_complete')
        assert resp.status_code == 400
        assert 'uniqueId parameter is required' in resp.data

    def test_with_invalid_participant_id_returns_error(self, webapp):
        resp = webapp.get('/worker_complete?uniqueId=nonsense')
        assert resp.status_code == 400
        assert 'UniqueId not found: nonsense' in resp.data

    def test_with_valid_participant_id_returns_success(self, a, webapp):
        participant = a.participant()

        resp = webapp.get('/worker_complete?uniqueId={}'.format(
            participant.unique_id)
        )
        assert resp.status_code == 200

    def test_sets_end_time(self, a, webapp, db_session):
        participant = a.participant()
        webapp.get('/worker_complete?uniqueId={}'.format(
            participant.unique_id)
        )
        assert db_session.merge(participant).end_time is not None

    def test_records_notification_if_debug_mode(self, a, webapp, active_config):
        from dallinger.models import Notification
        participant = a.participant()
        webapp.get('/worker_complete?uniqueId={}'.format(
            participant.unique_id)
        )
        assert Notification.query.one().event_type == u'AssignmentSubmitted'

    def test_records_notification_if_bot_recruiter(self, a, webapp, active_config):
        from dallinger.models import Notification
        active_config.extend({'recruiter': u'bots'})
        participant = a.participant()
        webapp.get('/worker_complete?uniqueId={}'.format(
            participant.unique_id)
        )
        assert Notification.query.one().event_type == u'BotAssignmentSubmitted'


@pytest.mark.usefixtures('experiment_dir', 'db_session')
class TestExperimentServer(object):
    worker_counter = 0
    hit_counter = 0
    assignment_counter = 0

    @pytest.fixture
    def participant_id(self, webapp):
        worker_id = self.worker_counter
        hit_id = self.hit_counter
        assignment_id = self.assignment_counter
        self.worker_counter += 1
        self.hit_counter += 1
        self.assignment_counter += 1

        resp = webapp.post('/participant/{}/{}/{}/debug'.format(
            worker_id, hit_id, assignment_id
        ))
        return json.loads(resp.data).get('participant', {}).get('id')

    @pytest.fixture
    def node_id(self, webapp, participant_id):
        resp = webapp.post('/node/{}'.format(participant_id))
        return json.loads(resp.data)['node']['id']

    @pytest.fixture
    def network_id(self, db_session):
        from dallinger.networks import Network
        net = Network()
        db_session.add(net)
        db_session.commit()

        return net.id

    def _update_participant_status(self, participant_id, status):
        from dallinger.models import Participant
        participant = Participant.query.get(participant_id)
        participant.status = status

    def test_success_response(self):
        from dallinger.experiment_server.experiment_server import success_response
        result = success_response(some_key="foo\nbar")
        as_dict = json.loads(result.response[0])
        assert as_dict == {u'status': u'success', u'some_key': u'foo\nbar'}

    def test_root(self, webapp):
        resp = webapp.get('/')
        assert resp.status_code == 404

    def test_favicon(self, webapp):
        resp = webapp.get('/favicon.ico')
        assert resp.content_type == 'image/x-icon'
        assert resp.content_length > 0

    def test_robots(self, webapp):
        resp = webapp.get('/robots.txt')
        assert 'User-agent' in resp.data

    def test_ad(self, webapp):
        resp = webapp.get('/ad', query_string={
            'hitId': 'debug',
            'assignmentId': '1',
            'mode': 'debug',
        })
        assert 'Psychology Experiment' in resp.data
        assert 'Please click the "Accept HIT" button on the Amazon site' not in resp.data
        assert 'Begin Experiment' in resp.data

    def test_ad_before_acceptance(self, webapp):
        resp = webapp.get('/ad', query_string={
            'hitId': 'debug',
            'assignmentId': 'ASSIGNMENT_ID_NOT_AVAILABLE',
            'mode': 'debug',
        })
        assert 'Please click the "Accept HIT" button on the Amazon site' in resp.data
        assert 'Begin Experiment' not in resp.data

    def test_ad_no_params(self, webapp):
        resp = webapp.get('/ad')
        assert resp.status_code == 500
        assert 'Psychology Experiment - Error' in resp.data

    def test_consent(self, webapp):
        resp = webapp.get('/consent', query_string={
            'hit_id': 'debug',
            'assignment_id': '1',
            'worker_id': '1',
            'mode': 'debug',
        })
        assert 'Informed Consent Form' in resp.data

    def test_participant_info(self, webapp, participant_id):
        resp = webapp.get('/participant/{}'.format(participant_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('participant').get('status') == u'working'

    def test_participant_invalid(self, webapp, participant_id):
        nonexistent_participant_id = 999
        resp = webapp.get('/participant/{}'.format(nonexistent_participant_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'error'
        assert 'no participant found' in data.get('html')

    def test_prevent_duplicate_participant_for_worker(self, webapp, participant_id):
        worker_id = self.worker_counter
        hit_id = self.hit_counter
        assignment_id = self.assignment_counter
        resp = webapp.post('/participant/{}/{}/{}/debug'.format(
            worker_id, hit_id, assignment_id
        ))

        assert resp.status_code == 200

        resp = webapp.post('/participant/{}/{}/{}/debug'.format(
            worker_id, hit_id, assignment_id
        ))

        assert resp.status_code == 403

    def test_notifies_recruiter_when_participant_joins(self, webapp):
        from dallinger.recruiters import Recruiter
        from dallinger.models import Participant

        worker_id = self.worker_counter
        hit_id = self.hit_counter
        assignment_id = self.assignment_counter
        class_to_patch = 'dallinger.experiment_server.experiment_server.Recruiter'

        with mock.patch(class_to_patch) as mock_rec_class:
            mock_recruiter = mock.Mock(spec=Recruiter)
            mock_rec_class.for_experiment.return_value = mock_recruiter
            webapp.post('/participant/{}/{}/{}/debug'.format(
                worker_id, hit_id, assignment_id
            ))
            args, _ = mock_recruiter.notify_recruited.call_args
            assert isinstance(args[0], Participant)

    def test_get_network(self, webapp, network_id):
        resp = webapp.get('/network/{}'.format(network_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('network').get('id') == network_id

    def test_get_network_invalid(self, webapp):
        nonexistent_network_id = 999
        resp = webapp.get('/network/{}'.format(nonexistent_network_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'error'
        assert 'no network found' in data.get('html')

    def test_node_vectors(self, webapp, node_id):
        resp = webapp.get('/node/{}/vectors'.format(node_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('vectors') == []

    def test_node_infos(self, webapp, node_id):
        resp = webapp.get('/node/{}/infos'.format(node_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('infos') == []

    def test_node_transmit_info_creates_transmission(self, db_session, webapp, node_id):
        from dallinger import models
        node_id_2 = self.node_id(webapp, self.participant_id(webapp))
        node1 = models.Node.query.get(node_id)
        info = models.Info(origin=node1)
        db_session.add(info)
        db_session.commit()

        resp = webapp.post(
            '/node/{}/transmit?what={}&to_whom={}'.format(node_id, info.id, node_id_2),
        )
        data = json.loads(resp.data)
        assert data['status'] == 'success'
        assert len(data['transmissions']) == 1
        assert data['transmissions'][0]['origin_id'] == node_id
        assert data['transmissions'][0]['destination_id'] == node_id_2

    def test_node_transmit_nonexistent_sender_returns_error(self, webapp):
        nonexistent_node_id = 999
        resp = webapp.post('/node/{}/transmit'.format(nonexistent_node_id))
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'node does not exist' in data['html']

    def test_node_transmit_content_and_no_target_does_nothing(self, webapp, node_id):
        resp = webapp.post('/node/{}/transmit'.format(node_id))
        data = json.loads(resp.data)
        assert data['status'] == 'success'
        assert data['transmissions'] == []

    def test_node_transmit_invalid_info_id_returns_error(self, webapp, node_id):
        nonexistent_info_id = 999
        resp = webapp.post('/node/{}/transmit?what={}'.format(node_id, nonexistent_info_id))
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'info does not exist' in data['html']

    def test_node_transmit_invalid_info_subclass_returns_error(self, webapp, node_id):
        nonexistent_subclass = 'Nonsense'
        resp = webapp.post('/node/{}/transmit?what={}'.format(node_id, nonexistent_subclass))
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'Nonsense not in experiment.known_classes' in data['html']

    def test_node_transmit_invalid_recipient_subclass_returns_error(self, db_session, webapp, node_id):
        from dallinger import models
        node1 = models.Node.query.get(node_id)
        info = models.Info(origin=node1)
        db_session.add(info)
        db_session.commit()
        nonexistent_subclass = 'Nonsense'
        resp = webapp.post('/node/{}/transmit?what={}&to_whom={}'.format(
            node_id, info.id, nonexistent_subclass)
        )
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'Nonsense not in experiment.known_classes' in data['html']

    def test_node_transmit_invalid_recipient_id_returns_error(self, db_session, webapp, node_id):
        from dallinger import models
        node1 = models.Node.query.get(node_id)
        info = models.Info(origin=node1)
        db_session.add(info)
        db_session.commit()
        nonexistent_id = 999
        resp = webapp.post('/node/{}/transmit?what={}&to_whom={}'.format(
            node_id, info.id, nonexistent_id)
        )
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'recipient Node does not exist' in data['html']

    def test_summary_no_participants(self, webapp):
        resp = webapp.get('/summary')
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('completed') is False
        assert data.get('unfilled_networks') == 1
        assert data.get('required_nodes') == 2
        assert data.get('nodes_remaining') == 2
        assert data.get('summary') == []

    def test_summary_one_participant(self, webapp, node_id):
        resp = webapp.get('/summary')
        data = json.loads(resp.data)
        assert data.get('completed') is False
        assert data.get('nodes_remaining') == 1
        worker_summary = data.get('summary')
        assert len(worker_summary) == 1
        assert worker_summary[0] == [u'working', 1]

    def test_summary_two_participants_and_still_working(self, webapp, node_id):
        self.node_id(webapp, self.participant_id(webapp))
        resp = webapp.get('/summary')
        data = json.loads(resp.data)
        assert data.get('completed') is False
        assert data.get('nodes_remaining') == 0
        worker_summary = data.get('summary')
        assert len(worker_summary) == 1
        assert worker_summary[0] == [u'working', 2]

    def test_summary_two_participants_with_different_status(self, webapp):
        p1_id = self.participant_id(webapp)
        p2_id = self.participant_id(webapp)
        self.node_id(webapp, p1_id)
        self.node_id(webapp, p2_id)

        self._update_participant_status(p1_id, 'submitted')
        self._update_participant_status(p2_id, 'approved')

        resp = webapp.get('/summary')
        data = json.loads(resp.data)
        assert data.get('completed') is True
        worker_summary = data.get('summary')
        assert len(worker_summary) == 2
        assert worker_summary[0] == [u'approved', 1]
        assert worker_summary[1] == [u'submitted', 1]

    def test_existing_experiment_property(self, webapp, participant_id):
        resp = webapp.get('/experiment/exists'.format(participant_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('exists') is True

    def test_nonexisting_experiment_property(self, webapp, participant_id):
        resp = webapp.get('/experiment/missing'.format(participant_id))
        assert resp.status_code == 404

    def test_not_found(self, webapp):
        resp = webapp.get('/BOGUS')
        assert resp.status_code == 404

    def test_launch(self, webapp):
        resp = webapp.post('/launch', {})
        assert resp.status_code == 200
        data = json.loads(resp.get_data())
        assert 'recruitment_msg' in data

    def test_launch_logging_fails(self, webapp):
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            bad_log = mock.Mock(side_effect=IOError)
            mock_exp = mock.Mock(log=bad_log)
            mock_class.return_value = mock_exp
            resp = webapp.post('/launch', {})

        assert resp.status_code == 500
        data = json.loads(resp.get_data())
        assert 'IOError writing to experiment log' in data['message']


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


end_time = datetime(2000, 1, 1)


@pytest.fixture
def experiment():
    from dallinger.experiment import Experiment
    experiment = mock.Mock(spec=Experiment)

    return experiment


@pytest.fixture
def standard_args(experiment):
    from dallinger.models import Participant
    from sqlalchemy.orm.scoping import scoped_session

    return {
        'participant': mock.Mock(spec_set=Participant, status="working"),
        'assignment_id': 'some assignment id',
        'experiment': experiment,
        'session': mock.Mock(spec_set=scoped_session),
        'config': {},
        'now': end_time
    }.copy()


class TestAssignmentSubmitted(object):

    @pytest.fixture
    def runner(self, standard_args):
        from dallinger.experiment_server.worker_events import AssignmentSubmitted
        experiment = standard_args['experiment']
        experiment.attention_check.return_value = True
        experiment.data_check.return_value = True
        experiment.bonus.return_value = 0.0
        experiment.bonus_reason.return_value = "You rock."
        standard_args['config'].update({'base_payment': 1.00})

        return AssignmentSubmitted(**standard_args)

    def test_calls_reward_bonus_if_experiment_returns_bonus_more_than_one_cent(self, runner):
        runner.experiment.bonus.return_value = .02
        runner()
        runner.experiment.recruiter.reward_bonus.assert_called_once_with(
            'some assignment id',
            .02,
            "You rock."
        )

    def test_no_reward_bonus_if_experiment_returns_bonus_less_than_one_cent(self, runner):
        runner()
        runner.experiment.recruiter.reward_bonus.assert_not_called()
        assert "NOT paying bonus" in str(runner.experiment.log.call_args_list)

    def test_sets_participant_bonus_regardless(self, runner):
        runner.experiment.bonus.return_value = .005
        runner()
        assert runner.participant.bonus == .005

    def test_approve_hit_called_on_recruiter(self, runner):
        runner()
        runner.experiment.recruiter.approve_hit.assert_called_once_with(
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
        runner.experiment.recruiter.recruit.assert_called_once_with(
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
        runner.experiment.recruiter.approve_hit.assert_called_once_with(
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
