import json
import mock
import pytest
from datetime import datetime
from dallinger import models


@pytest.mark.usefixtures('experiment_dir')
class TestAppConfiguration(object):

    def test_config_gets_loaded_before_first_request(self, webapp):
        from dallinger.config import get_config
        conf = get_config()
        conf.clear()
        webapp.get('/')
        assert conf.ready


@pytest.mark.usefixtures('experiment_dir')
class TestAdvertisement(object):

    def test_returns_error_without_hitId_and_assignmentId(self, webapp):
        resp = webapp.get('/ad')
        assert resp.status_code == 500
        assert 'hit_assign_worker_id_not_set_in_mturk' in resp.data

    def test_with_no_worker_id_and_nonexistent_hit_and_assignment(self, webapp):
        resp = webapp.get('/ad?hitId=foo&assignmentId=bar')
        assert 'Thanks for accepting this HIT.' in resp.data

    def test_with_nonexistent_hit_worker_and_assignment(self, webapp):
        resp = webapp.get('/ad?hitId=foo&assignmentId=bar&workerId=baz')
        assert 'Thanks for accepting this HIT.' in resp.data

    def test_checks_browser_exclusion_rules(self, webapp, active_config):
        active_config.extend({'browser_exclude_rule': u'tablet, bot'})
        resp = webapp.get(
            '/ad?hitId=foo&assignmentId=bar',
            environ_base={'HTTP_USER_AGENT': 'Googlebot/2.1 (+http://www.google.com/bot.html)'}
        )
        assert resp.status_code == 500
        assert 'browser_type_not_allowed' in resp.data

    def test_still_working_in_debug_mode_returns_error(self, a, webapp):
        p = a.participant()
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, p.assignment_id, p.worker_id
            )
        )
        assert resp.status_code == 500
        assert 'already_started_exp_mturk' in resp.data

    def test_still_working_in_sandbox_mode_returns_error(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox'})
        p = a.participant()
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, p.assignment_id, p.worker_id
            )
        )
        assert resp.status_code == 500
        assert 'already_started_exp_mturk' in resp.data

    def test_previously_completed_same_exp_fails_if_not_debug(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox'})
        p = a.participant()
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, 'some_previous_assignmentID', p.worker_id
            )
        )
        assert resp.status_code == 500
        assert 'already_did_exp_hit' in resp.data

    def test_previously_completed_same_exp_ok_if_debug(self, a, webapp, active_config):
        p = a.participant()
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, 'some_previous_assignmentID', p.worker_id
            )
        )
        assert 'Thanks for accepting this HIT.' in resp.data

    def test_submitted_hit_shows_thanks_page_in_debug(self, a, webapp):
        p = a.participant()
        p.status = u'submitted'
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, p.assignment_id, p.worker_id
            )
        )
        assert 'If this were a real HIT, you would push a button to finish' in resp.data

    def test_shows_thanks_page_if_participant_is_working_but_has_end_time(self, a, webapp):
        p = a.participant()
        p.end_time = datetime.now()
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, p.assignment_id, p.worker_id
            )
        )
        assert 'If this were a real HIT, you would push a button to finish' in resp.data

    def test_working_hit_shows_thanks_page_in_sandbox_mode(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox'})
        p = a.participant()
        p.end_time = datetime.now()
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, p.assignment_id, p.worker_id
            )
        )
        assert 'action="https://workersandbox.mturk.com/mturk/externalSubmit"' in resp.data

    def test_working_hit_shows_thanks_page_in_live_mode(self, a, webapp, active_config):
        active_config.extend({'mode': u'live'})
        p = a.participant()
        p.end_time = datetime.now()
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, p.assignment_id, p.worker_id
            )
        )
        assert 'action="https://www.mturk.com/mturk/externalSubmit"' in resp.data

    @pytest.mark.skip(reason="fails pending support for different recruiters")
    def test_submitted_hit_shows_thanks_page_in_sandbox(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox'})
        p = a.participant()
        p.status = u'submitted'
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, p.assignment_id, p.worker_id
            )
        )
        assert 'To complete the HIT, simply press the button below.' in resp.data

    def test_recruiter_without_external_submission(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox', 'recruiter': u'CLIRecruiter'})
        p = a.participant()
        p.status = u'submitted'
        resp = webapp.get(
            '/ad?hitId={}&assignmentId={}&workerId={}'.format(
                p.hit_id, p.assignment_id, p.worker_id
            )
        )
        assert "You're all done!" in resp.data


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

    def test_nonworking_mturk_participants_accepted_if_debug(self, a, webapp, active_config):
        participant = a.participant()
        participant.status = 'submitted'
        webapp.post(
            '/question/{}?question=q&response=r&number=1'.format(participant.id)
        )
        assert models.Question.query.all()

    def test_nonworking_mturk_participants_denied_if_not_debug(self, a, webapp, active_config):
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

    def test_nonworking_nonmturk_participants_accepted(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox', 'recruiter': u'CLIRecruiter'})
        participant = a.participant()
        participant.status = 'submitted'
        webapp.post(
            '/question/{}?question=q&response=r&number=1'.format(participant.id)
        )
        assert models.Question.query.all()


@pytest.mark.usefixtures('experiment_dir', 'db_session')
class TestWorkerComplete(object):

    def test_with_no_participant_id_returns_error(self, webapp):
        resp = webapp.get('/worker_complete')
        assert resp.status_code == 400
        assert 'participantId parameter is required' in resp.data

    def test_with_invalid_participant_id_returns_error(self, webapp):
        resp = webapp.get('/worker_complete?participant_id=-1')
        assert resp.status_code == 400
        assert 'ParticipantId not found: -1' in resp.data

    def test_with_valid_participant_id_returns_success(self, a, webapp):
        resp = webapp.get('/worker_complete?participant_id={}'.format(
            a.participant().id)
        )
        assert resp.status_code == 200

    def test_sets_end_time(self, a, webapp, db_session):
        participant = a.participant()
        webapp.get('/worker_complete?participant_id={}'.format(
            participant.id)
        )
        assert db_session.merge(participant).end_time is not None

    def test_records_notification_if_debug_mode(self, a, webapp):
        webapp.get('/worker_complete?participant_id={}'.format(
            a.participant().id)
        )
        assert models.Notification.query.one().event_type == u'AssignmentSubmitted'

    def test_records_notification_if_bot_recruiter(self, a, webapp, active_config):
        active_config.extend({'recruiter': u'bots'})
        webapp.get('/worker_complete?participant_id={}'.format(
            a.participant().id)
        )
        assert models.Notification.query.one().event_type == u'BotAssignmentSubmitted'

    def test_records_no_notification_mturk_recruiter_and_nondebug(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox'})
        webapp.get('/worker_complete?participant_id={}'.format(
            a.participant().id)
        )
        assert models.Notification.query.all() == []

    def test_records_notification_for_non_mturk_recruiter(self, a, webapp, active_config):
        active_config.extend({'mode': u'sandbox', 'recruiter': u'CLIRecruiter'})
        webapp.get('/worker_complete?participant_id={}'.format(
            a.participant().id)
        )
        assert models.Notification.query.one().event_type == u'AssignmentSubmitted'


@pytest.mark.usefixtures('experiment_dir', 'db_session')
class TestWorkerFailed(object):

    def test_with_no_participant_id_returns_error(self, webapp):
        resp = webapp.get('/worker_failed')
        assert resp.status_code == 400
        assert 'participantId parameter is required' in resp.data

    def test_with_invalid_participant_id_returns_error(self, webapp):
        resp = webapp.get('/worker_failed?participant_id=-1')
        assert resp.status_code == 400
        assert 'ParticipantId not found: -1' in resp.data

    def test_with_valid_participant_id_returns_success(self, a, webapp):
        resp = webapp.get('/worker_failed?participant_id={}'.format(
            a.participant().id)
        )
        assert resp.status_code == 200

    def test_sets_end_time(self, a, webapp, db_session):
        participant = a.participant()
        webapp.get('/worker_failed?participant_id={}'.format(
            participant.id)
        )
        assert db_session.merge(participant).end_time is not None

    def test_records_notification_if_bot_recruiter(self, a, webapp, active_config):
        active_config.extend({'recruiter': u'bots'})
        webapp.get('/worker_failed?participant_id={}'.format(
            a.participant().id)
        )
        assert models.Notification.query.one().event_type == u'BotAssignmentRejected'

    def test_records_no_notification_if_mturk_recruiter(self, a, webapp):
        webapp.get('/worker_failed?participant_id={}'.format(
            a.participant().id)
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

        with mock.patch('dallinger.experiment_server.experiment_server.recruiters') as recruiters:
            mock_recruiter = mock.Mock(spec=Recruiter)
            recruiters.for_experiment.return_value = mock_recruiter
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
        network = a.star()
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
        network = a.star()
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
        network = a.star()
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
class TestParticipantNodeCreationRoute(object):

    def test_with_invalid_participant_id_returns_error(self, webapp):
        resp = webapp.post('/node/123')
        assert resp.status_code == 403
        assert '/node POST no participant found' in resp.data

    def test_with_valid_participant_creates_participant_node(self, a, webapp):
        participant_id = a.participant().id
        resp = webapp.post('/node/{}'.format(participant_id))
        data = json.loads(resp.data)
        assert data.get('node').get('participant_id') == participant_id

    def test_with_valid_participant_adds_node_to_network(self, a, webapp):
        from dallinger.networks import Star
        participant_id = a.participant().id
        resp = webapp.post('/node/{}'.format(participant_id))
        data = json.loads(resp.data)
        assert Star.query.one().nodes()[0].id == data['node']['network_id']

    def test_participant_status_not_working_returns_error(self, a, webapp):
        participant = a.participant()
        participant.status = 'submitted'
        resp = webapp.post('/node/{}'.format(participant.id))
        assert 'Error type: /node POST, status = submitted' in resp.data

    def test_no_network_for_participant_returns_error(self, a, webapp):
        participant = a.participant()
        # Assign the participant to a node and fill the network:
        a.node(participant=participant, network=a.star(max_size=1))
        resp = webapp.post('/node/{}'.format(participant.id))
        assert resp.data == '{"status": "error"}'


@pytest.mark.usefixtures('experiment_dir')
class TestRequestParameter(object):

    @pytest.fixture
    def rp(self):
        from dallinger.experiment_server.experiment_server import request_parameter
        return request_parameter

    def test_returns_existing_simple_param(self, test_request, rp):
        with test_request('/robots.txt?foo=bar'):
            assert rp('foo') == 'bar'

    def test_returns_default_for_missing_param(self, test_request, rp):
        with test_request('/robots.txt'):
            assert rp('foo', default='bar') == 'bar'

    def test_returns_none_for_missing_optional_param(self, test_request, rp):
        with test_request('/robots.txt'):
            assert rp('foo', optional=True) is None

    def test_returns_error_for_missing_param_with_no_default(self, test_request, rp):
        with test_request('/robots.txt'):
            assert 'foo not specified' in rp('foo').data

    def test_marshalls_based_on_parameter_type(self, test_request, rp):
        with test_request('/robots.txt?foo=1'):
            assert rp('foo', parameter_type='int') == 1

    def test_failure_marshalling_type_returns_error(self, test_request, rp):
        with test_request('/robots.txt?foo=bar'):
            assert 'non-numeric foo: bar' in rp('foo', parameter_type='int').data

    def test_returns_class_objects_for_experiment_known_classes(self, test_request, rp):
        with test_request('/robots.txt?foo=Info'):
            assert rp('foo', parameter_type='known_class') == models.Info

    def test_returns_error_for_nonexistent_known_class(self, test_request, rp):
        with test_request('/robots.txt?foo=BadClass'):
            result = rp('foo', parameter_type='known_class')
            assert 'unknown_class: BadClass' in result.data

    def test_marshalls_valid_boolean_strings(self, test_request, rp):
        with test_request('/robots.txt?foo=True'):
            result = rp('foo', parameter_type='bool')
            assert isinstance(result, bool)

    def test_returns_error_for_invalid_boolean_strings(self, test_request, rp):
        with test_request('/robots.txt?foo=BadBool'):
            result = rp('foo', parameter_type='bool')
            assert 'non-boolean foo: BadBool' in result.data

    def test_returns_error_for_unknown_parameter_type(self, test_request, rp):
        with test_request('/robots.txt?foo=True'):
            result = rp('foo', parameter_type='bad_type')
            assert 'unknown parameter type: bad_type' in result.data


@pytest.mark.usefixtures('experiment_dir', 'db_session')
class TestNodeRoutePOST(object):

    def test_node_transmit_info_creates_transmission(self, a, webapp, db_session):
        network = a.star()
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
class TestNodeNeighbors(object):

    def test_returns_error_on_invalid_paramter(self, webapp):
        resp = webapp.get('/node/123/neighbors?node_type=BadClass')
        assert 'unknown_class: BadClass for parameter node_type' in resp.data

    def test_returns_error_for_invalid_node_id(self, webapp):
        resp = webapp.get('/node/123/neighbors')
        assert 'node 123 does not exist' in resp.data

    def test_includes_failed_param_if_request_includes_it(self, a, webapp):
        node = a.node()
        resp = webapp.get('/node/{}/neighbors?failed=False'.format(node.id))
        assert 'You should not pass a failed argument to neighbors().' in resp.data

    def test_finds_neighbor_nodes(self, a, webapp):
        network = a.network()
        node1 = a.node(network=network)
        node2 = a.node(network=network)
        node1.connect(node2)

        resp = webapp.get('/node/{}/neighbors'.format(node1.id))
        data = json.loads(resp.data)
        assert data['nodes'][0]['id'] == node2.id

    def test_pings_experiment(self, a, webapp):
        node = a.node()
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            mock_exp = mock.Mock(name="the experiment")
            mock_class.return_value = mock_exp
            webapp.get('/node/{}/neighbors'.format(node.id))
            mock_exp.node_get_request.assert_called_once_with(
                node=node,
                nodes=[]
            )

    def test_returns_error_if_experiment_ping_fails(self, a, webapp):
        node = a.node()
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            mock_exp = mock.Mock(name="the experiment")
            mock_exp.node_get_request.side_effect = Exception("boom!")
            mock_class.return_value = mock_exp
            resp = webapp.get('/node/{}/neighbors'.format(node.id))

        assert 'exp.node_get_request' in resp.data


@pytest.mark.usefixtures('experiment_dir')
class TestNodeReceivedInfos(object):

    def test_returns_error_on_invalid_paramter(self, webapp):
        resp = webapp.get('/node/123/received_infos?info_type=BadClass')
        assert 'unknown_class: BadClass for parameter info_type' in resp.data

    def test_returns_error_for_invalid_node_id(self, webapp):
        resp = webapp.get('/node/123/received_infos')
        assert '/node/infos, node 123 does not exist' in resp.data

    def test_finds_received_infos(self, a, webapp):
        net = a.network()
        sender = a.node(network=net)
        receiver = a.node(network=net)
        sender.connect(direction="to", whom=receiver)
        info = a.info(origin=sender, contents="foo")
        sender.transmit(what=sender.infos()[0], to_whom=receiver)
        receiver.receive()

        resp = webapp.get('/node/{}/received_infos'.format(receiver.id))
        data = json.loads(resp.data)

        assert data['infos'][0]['id'] == info.id
        assert data['infos'][0]['contents'] == 'foo'

    def test_returns_empty_if_no_infos_received_by_node(self, a, webapp):
        net = a.network()
        node = a.node(network=net)

        resp = webapp.get('/node/{}/received_infos'.format(node.id))
        data = json.loads(resp.data)

        assert data['infos'] == []

    def test_pings_experiment(self, a, webapp):
        node = a.node()
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            mock_exp = mock.Mock(name="the experiment")
            mock_class.return_value = mock_exp
            webapp.get('/node/{}/received_infos'.format(node.id))
            mock_exp.info_get_request.assert_called_once_with(
                node=node,
                infos=[]
            )

    def test_returns_error_if_experiment_ping_fails(self, a, webapp):
        node = a.node()
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            mock_exp = mock.Mock(name="the experiment")
            mock_exp.info_get_request.side_effect = Exception("boom!")
            mock_class.return_value = mock_exp
            resp = webapp.get('/node/{}/received_infos'.format(node.id))

        assert 'info_get_request error' in resp.data


@pytest.mark.usefixtures('experiment_dir')
class TestTransformationGet(object):

    def test_returns_error_on_invalid_paramter(self, webapp):
        resp = webapp.get('/node/123/transformations?transformation_type=BadClass')
        assert 'unknown_class: BadClass for parameter transformation_type' in resp.data

    def test_returns_error_for_invalid_node_id(self, webapp):
        resp = webapp.get('/node/123/transformations')
        assert 'node 123 does not exist' in resp.data

    def test_finds_transformations(self, a, webapp):
        node = a.node()
        node_id = node.id  # save so we don't have to merge sessions
        node.replicate(a.info(origin=node))

        resp = webapp.get(
            '/node/{}/transformations?transformation_type=Replication'.format(node_id)
        )
        data = json.loads(resp.data)
        assert data['transformations'][0]['node_id'] == node_id

    def test_pings_experiment(self, a, webapp):
        node = a.node()
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            mock_exp = mock.Mock(name="the experiment")
            mock_class.return_value = mock_exp
            webapp.get('/node/{}/transformations'.format(node.id))
            mock_exp.transformation_get_request.assert_called_once_with(
                node=node,
                transformations=[]
            )

    def test_returns_error_if_experiment_ping_fails(self, a, webapp):
        node = a.node()
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            mock_exp = mock.Mock(name="the experiment")
            mock_exp.transformation_get_request.side_effect = Exception("boom!")
            mock_class.return_value = mock_exp
            resp = webapp.get('/node/{}/transformations'.format(node.id))
        assert '/node/transformations GET failed' in resp.data


@pytest.mark.usefixtures('experiment_dir')
class TestTransformationPost(object):

    def test_returns_error_on_invalid_paramter(self, webapp):
        resp = webapp.post('/transformation/123/123/123?transformation_type=BadClass')
        assert 'unknown_class: BadClass for parameter transformation_type' in resp.data

    def test_returns_error_for_invalid_node_id(self, webapp):
        resp = webapp.post('/transformation/123/123/123')
        assert 'node 123 does not exist' in resp.data

    def test_returns_error_for_invalid_info_in_id(self, a, webapp):
        node = a.node()
        resp = webapp.post('/transformation/{}/123/123'.format(node.id))
        assert 'info_in 123 does not exist' in resp.data

    def test_returns_error_for_invalid_info_out_id(self, a, webapp):
        node = a.node()
        info = a.info(origin=node)
        resp = webapp.post('/transformation/{}/{}/123'.format(node.id, info.id))
        assert 'info_out 123 does not exist' in resp.data

    def test_creates_transformation(self, a, webapp):
        node = a.node()
        info_in = a.info(origin=node)
        info_out = a.info(origin=node)
        info_out_id = info_out.id  # save to avoid merging sessions
        resp = webapp.post(
            '/transformation/{}/{}/{}'.format(node.id, info_in.id, info_out.id)
        )
        data = json.loads(resp.data)
        assert data['transformation']['info_out_id'] == info_out_id

    def test_pings_experiment(self, a, webapp):
        node = a.node()
        info_in = a.info(origin=node)
        info_out = a.info(origin=node)
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            mock_exp = mock.Mock(name="the experiment")
            mock_class.return_value = mock_exp
            webapp.post(
                '/transformation/{}/{}/{}'.format(node.id, info_in.id, info_out.id)
            )
            mock_exp.transformation_post_request.assert_called()

    def test_returns_error_if_experiment_ping_fails(self, a, webapp):
        node = a.node()
        info_in = a.info(origin=node)
        info_out = a.info(origin=node)
        with mock.patch('dallinger.experiment_server.experiment_server.Experiment') as mock_class:
            mock_exp = mock.Mock(name="the experiment")
            mock_exp.transformation_post_request.side_effect = Exception("boom!")
            mock_class.return_value = mock_exp
            resp = webapp.post(
                '/transformation/{}/{}/{}'.format(node.id, info_in.id, info_out.id)
            )
        assert '/transformation POST failed' in resp.data


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
