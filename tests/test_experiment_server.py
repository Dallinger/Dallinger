import json
import mock
import pytest
from datetime import datetime
from dallinger import models


@pytest.mark.usefixtures('experiment_dir')
class TestQuestion(object):

    def test_with_no_participant_id_fails_to_match_route_returns_405(self, webapp):
        # I found this surprising, so leaving the test here.
        resp = webapp.post('/question')
        assert resp.status_code == 405

    def test_with_invalid_participant_id_returns_error(self, webapp):
        resp = webapp.post('/question/123')
        assert resp.status_code == 403

    def test_working_participants_accepted(self, a, webapp):
        webapp.post(
            '/question/{}?question=q&response=r&number=1'.format(a.participant().id)
        )
        assert models.Question.query.all()

    def test_nonworking_participants_accepted_if_debug(self, a, webapp):
        participant = a.participant()
        participant.status = 'submitted'
        webapp.post(
            '/question/{}?question=q&response=r&number=1'.format(participant.id)
        )
        assert models.Question.query.all()

    def test_nonworking_participants_denied_if_not_debug(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox'})
        participant = a.participant()
        participant.status = 'submitted'
        webapp.post(
            '/question/{}?question=q&response=r&number=1'.format(participant.id)
        )
        assert models.Question.query.all() == []

    def test_invalid_question_data_returns_error(self, a, webapp):
        resp = webapp.post(
            '/question/{}?question=q&response=r&number=not a number'.format(
                a.participant().id
            )
        )
        assert resp.status_code == 400
        assert 'non-numeric number: not a number' in resp.data


@pytest.mark.usefixtures('experiment_dir', 'db_session')
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
        resp = webapp.get('/worker_complete?uniqueId={}'.format(
            a.participant().unique_id)
        )
        assert resp.status_code == 200

    def test_sets_end_time(self, a, webapp, db_session):
        participant = a.participant()
        webapp.get('/worker_complete?uniqueId={}'.format(
            participant.unique_id)
        )
        assert db_session.merge(participant).end_time is not None

    def test_records_notification_if_debug_mode(self, a, webapp):
        webapp.get('/worker_complete?uniqueId={}'.format(
            a.participant().unique_id)
        )
        assert models.Notification.query.one().event_type == u'AssignmentSubmitted'

    def test_records_notification_if_bot_recruiter(self, a, webapp, active_config):
        active_config.extend({'recruiter': u'bots'})
        webapp.get('/worker_complete?uniqueId={}'.format(
            a.participant().unique_id)
        )
        assert models.Notification.query.one().event_type == u'BotAssignmentSubmitted'

    def test_records_no_notification_mturk_recruiter_and_nondebug(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox'})
        webapp.get('/worker_complete?uniqueId={}'.format(
            a.participant().unique_id)
        )
        assert models.Notification.query.all() == []

    def test_records_notification_for_non_mturk_recruiter(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox', 'recruiter': u'CLIRecruiter'})
        webapp.get('/worker_complete?uniqueId={}'.format(
            a.participant().unique_id)
        )
        assert models.Notification.query.one().event_type == u'AssignmentSubmitted'


@pytest.mark.usefixtures('experiment_dir', 'db_session')
class TestWorkerFailed(object):

    def test_with_no_participant_id_returns_error(self, webapp):
        resp = webapp.get('/worker_failed')
        assert resp.status_code == 400
        assert 'uniqueId parameter is required' in resp.data

    def test_with_invalid_participant_id_returns_error(self, webapp):
        resp = webapp.get('/worker_failed?uniqueId=nonsense')
        assert resp.status_code == 400
        assert 'UniqueId not found: nonsense' in resp.data

    def test_with_valid_participant_id_returns_success(self, a, webapp):
        resp = webapp.get('/worker_failed?uniqueId={}'.format(
            a.participant().unique_id)
        )
        assert resp.status_code == 200

    def test_sets_end_time(self, a, webapp, db_session):
        participant = a.participant()
        webapp.get('/worker_failed?uniqueId={}'.format(
            participant.unique_id)
        )
        assert db_session.merge(participant).end_time is not None

    def test_records_notification_if_bot_recruiter(self, a, webapp, active_config):
        active_config.extend({'recruiter': u'bots'})
        webapp.get('/worker_failed?uniqueId={}'.format(
            a.participant().unique_id)
        )
        assert models.Notification.query.one().event_type == u'BotAssignmentRejected'

    def test_records_no_notification_if_mturk_recruiter(self, a, webapp):
        webapp.get('/worker_failed?uniqueId={}'.format(
            a.participant().unique_id)
        )
        assert models.Notification.query.all() == []


@pytest.mark.usefixtures('experiment_dir')
class TestSimpleGETRoutes(object):

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

    def test_consent(self, webapp):
        resp = webapp.get('/consent', query_string={
            'hit_id': 'debug',
            'assignment_id': '1',
            'worker_id': '1',
            'mode': 'debug',
        })
        assert 'Informed Consent Form' in resp.data

    def test_not_found(self, webapp):
        resp = webapp.get('/BOGUS')
        assert resp.status_code == 404

    def test_existing_experiment_property(self, webapp):
        resp = webapp.get('/experiment/exists')
        data = json.loads(resp.data)
        assert data == {u'exists': True, u'status': u'success'}

    def test_nonexisting_experiment_property(self, webapp):
        resp = webapp.get('/experiment/missing')
        assert resp.status_code == 404


@pytest.mark.usefixtures('experiment_dir')
class TestAdRoute(object):

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


@pytest.mark.usefixtures('experiment_dir', 'db_session')
class TestParticipantRoute(object):

    def test_participant_info(self, a, webapp):
        p = a.participant()
        resp = webapp.get('/participant/{}'.format(p.id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('participant').get('status') == u'working'

    def test_participant_invalid(self, webapp):
        nonexistent_participant_id = 999
        resp = webapp.get('/participant/{}'.format(nonexistent_participant_id))
        data = json.loads(resp.data)
        assert data.get('status') == 'error'
        assert 'no participant found' in data.get('html')

    def test_creates_participant_if_worker_id_unique(self, webapp):
        worker_id = '1'
        hit_id = '1'
        assignment_id = '1'
        resp = webapp.post('/participant/{}/{}/{}/debug'.format(
            worker_id, hit_id, assignment_id
        ))

        assert resp.status_code == 200

    def test_prevent_duplicate_participant_for_worker(self, a, webapp):
        p = a.participant()
        resp = webapp.post('/participant/{}/{}/{}/debug'.format(
            p.worker_id, p.hit_id, p.assignment_id
        ))

        assert resp.status_code == 403

    def test_notifies_recruiter_when_participant_joins(self, webapp):
        from dallinger.recruiters import Recruiter
        from dallinger.models import Participant

        worker_id = '1'
        hit_id = '1'
        assignment_id = '1'
        class_to_patch = 'dallinger.experiment_server.experiment_server.Recruiter'

        with mock.patch(class_to_patch) as mock_rec_class:
            mock_recruiter = mock.Mock(spec=Recruiter)
            mock_rec_class.for_experiment.return_value = mock_recruiter
            webapp.post('/participant/{}/{}/{}/debug'.format(
                worker_id, hit_id, assignment_id
            ))
            args, _ = mock_recruiter.notify_recruited.call_args
            assert isinstance(args[0], Participant)


@pytest.mark.usefixtures('experiment_dir')
class TestSummaryRoute(object):

    def test_summary_no_participants(self, a, webapp):
        resp = webapp.get('/summary')
        data = json.loads(resp.data)
        assert data == {
            u'completed': False,
            u'nodes_remaining': 2,
            u'required_nodes': 2,
            u'status': u'success',
            u'summary': [],
            u'unfilled_networks': 1
        }

    def test_summary_one_participant(self, a, webapp):
        network = a.star_network()
        network.add_node(a.node(network=network, participant=a.participant()))
        resp = webapp.get('/summary')
        data = json.loads(resp.data)
        assert data == {
            u'completed': False,
            u'nodes_remaining': 1,
            u'required_nodes': 2,
            u'status': u'success',
            u'summary': [[u'working', 1]],
            u'unfilled_networks': 1
        }

    def test_summary_two_participants_and_still_working(self, a, webapp):
        network = a.star_network()
        network.add_node(a.node(network=network, participant=a.participant()))
        network.add_node(a.node(network=network, participant=a.participant()))

        resp = webapp.get('/summary')
        data = json.loads(resp.data)
        assert data == {
            u'completed': False,
            u'nodes_remaining': 0,
            u'required_nodes': 0,
            u'status': u'success',
            u'summary': [[u'working', 2]],
            u'unfilled_networks': 0
        }

    def test_summary_two_participants_with_different_status(self, a, webapp):
        p1 = a.participant()
        p2 = a.participant()
        network = a.star_network()
        network.add_node(a.node(network=network, participant=p1))
        network.add_node(a.node(network=network, participant=p2))
        p1.status = 'submitted'
        p2.status = 'approved'

        resp = webapp.get('/summary')
        data = json.loads(resp.data)
        assert data == {
            u'completed': True,
            u'nodes_remaining': 0,
            u'required_nodes': 0,
            u'status': u'success',
            u'summary': [[u'approved', 1], [u'submitted', 1]],
            u'unfilled_networks': 0
        }


@pytest.mark.usefixtures('experiment_dir')
class TestNetworkRoute(object):

    def test_get_network(self, a, webapp):
        network = a.network()
        resp = webapp.get('/network/{}'.format(network.id))
        data = json.loads(resp.data)
        assert data.get('network').get('id') == network.id

    def test_get_network_invalid_returns_error(self, webapp):
        nonexistent_network_id = 999
        resp = webapp.get('/network/{}'.format(nonexistent_network_id))
        data = json.loads(resp.data)
        assert 'no network found' in data.get('html')

    def test_get_network_includes_error_message(self, webapp):
        nonexistent_network_id = 999
        resp = webapp.get('/network/{}'.format(nonexistent_network_id))
        data = json.loads(resp.data)
        assert 'no network found' in data.get('html')


@pytest.mark.usefixtures('experiment_dir')
class TestNodeRouteGET(object):

    def test_node_vectors(self, a, webapp):
        node = a.node()
        resp = webapp.get('/node/{}/vectors'.format(node.id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('vectors') == []

    def test_node_infos(self, a, webapp):
        node = a.node()
        resp = webapp.get('/node/{}/infos'.format(node.id))
        data = json.loads(resp.data)
        assert data.get('status') == 'success'
        assert data.get('infos') == []


@pytest.mark.usefixtures('experiment_dir', 'db_session')
class TestNodeRoutePOST(object):

    def test_node_transmit_info_creates_transmission(self, a, webapp, db_session):
        network = a.star_network()
        node1 = a.node(network=network, participant=a.participant())
        network.add_node(node1)
        node2 = a.node(network=network, participant=a.participant())
        network.add_node(node2)
        info = a.info(origin=node1)
        resp = webapp.post(
            '/node/{}/transmit?what={}&to_whom={}'.format(node1.id, info.id, node2.id),
        )
        data = json.loads(resp.data)
        assert len(data['transmissions']) == 1
        assert data['transmissions'][0]['origin_id'] == db_session.merge(node1).id
        assert data['transmissions'][0]['destination_id'] == db_session.merge(node2).id

    def test_node_transmit_nonexistent_sender_returns_error(self, webapp):
        nonexistent_node_id = 999
        resp = webapp.post('/node/{}/transmit'.format(nonexistent_node_id))
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'node does not exist' in data['html']

    def test_node_transmit_content_and_no_target_does_nothing(self, a, webapp):
        node = a.node()
        resp = webapp.post('/node/{}/transmit'.format(node.id))
        data = json.loads(resp.data)
        assert data['status'] == 'success'
        assert data['transmissions'] == []

    def test_node_transmit_invalid_info_id_returns_error(self, a, webapp):
        node = a.node()
        nonexistent_info_id = 999
        resp = webapp.post('/node/{}/transmit?what={}'.format(node.id, nonexistent_info_id))
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'info does not exist' in data['html']

    def test_node_transmit_invalid_info_subclass_returns_error(self, a, webapp):
        node = a.node()
        nonexistent_subclass = 'Nonsense'
        resp = webapp.post('/node/{}/transmit?what={}'.format(node.id, nonexistent_subclass))
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'Nonsense not in experiment.known_classes' in data['html']

    def test_node_transmit_invalid_recipient_subclass_returns_error(self, a, webapp):
        node = a.node()
        info = a.info(origin=node)
        nonexistent_subclass = 'Nonsense'
        resp = webapp.post('/node/{}/transmit?what={}&to_whom={}'.format(
            node.id, info.id, nonexistent_subclass)
        )
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'Nonsense not in experiment.known_classes' in data['html']

    def test_node_transmit_invalid_recipient_id_returns_error(self, a, webapp):
        node = a.node()
        info = a.info(origin=node)
        nonexistent_id = 999
        resp = webapp.post('/node/{}/transmit?what={}&to_whom={}'.format(
            node.id, info.id, nonexistent_id)
        )
        data = json.loads(resp.data)
        assert data['status'] == 'error'
        assert 'recipient Node does not exist' in data['html']


@pytest.mark.usefixtures('experiment_dir')
class TestLaunchRoute(object):

    def test_launch(self, webapp):
        resp = webapp.post('/launch', {})
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
        assert data == {
            u'message': u'IOError writing to experiment log: ',
            u'status': u'error'
        }


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

    def test_uses_assignment_id(self, a, worker_func):
        participant = a.participant()

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

    def test_uses_participant_id(self, a, worker_func):
        participant = a.participant()

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
