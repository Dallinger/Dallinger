from datetime import datetime
from unittest import mock

import pytest

from dallinger.models import Participant


def is_uuid(thing):
    return len(thing) == 36


@pytest.mark.usefixtures("active_config")
class TestExperimentBaseClass(object):
    @pytest.fixture
    def klass(self):
        from dallinger.experiment import Experiment

        return Experiment

    @pytest.fixture
    def exp(self, klass):
        return klass()

    @pytest.fixture
    def exp_with_session(self, klass, db_session):
        return klass(db_session)

    def test_recruiter_delegates(self, exp, active_config):
        with mock.patch("dallinger.experiment.recruiters") as mock_module:
            exp.recruiter
            mock_module.from_config.assert_called_once_with(active_config)

    def test_make_uuid_generates_random_id_if_passed_none(self, klass):
        assert is_uuid(klass.make_uuid(None))

    def test_make_uuid_generates_random_id_if_passed_nonuuid(self, klass):
        assert is_uuid(klass.make_uuid("None"))

    def test_make_uuid_echos_a_valid_uuid(self, klass):
        valid = "8a61fc2e-43ae-cc13-fd1e-aa8f676096cc"
        assert klass.make_uuid(valid) == valid

    def test_quorum_zero_by_default(self, exp):
        assert exp.quorum == 0

    def test_not_overrecruited_with_default_zero_quorum(self, exp):
        assert not exp.is_overrecruited(waiting_count=1)

    def test_is_overrecruited_if_waiting_exceeds_quorum(self, exp):
        exp.quorum = 1
        assert exp.is_overrecruited(waiting_count=2)

    def test_not_overrecruited_if_waiting_equal_to_quorum(self, exp):
        exp.quorum = 1
        assert not exp.is_overrecruited(waiting_count=1)

    def test_create_participant(self, exp_with_session):
        from dallinger.models import Participant

        assert len(Participant.query.filter(Participant.hit_id == "1").all()) == 0

        p = exp_with_session.create_participant(
            "1", "1", "1", "debug", entry_information={"some_key": "some_value"}
        )

        assert isinstance(p, Participant)
        assert p.hit_id == "1"
        assert p.worker_id == "1"
        assert p.assignment_id == "1"
        assert p.recruiter_id == "hotair"
        assert p.entry_information == {"some_key": "some_value"}
        assert len(Participant.query.filter(Participant.hit_id == "1").all()) == 1

    def test_create_participant_with_custom_class(self, exp_with_session):
        from dallinger.models import Participant

        class MyParticipant(Participant):
            pass

        exp_with_session.participant_constructor = MyParticipant
        p = exp_with_session.create_participant("1", "1", "1", "debug")

        assert isinstance(p, MyParticipant)

    def test_load_participant(self, exp, a):
        p = a.participant()
        assert exp.load_participant(p.assignment_id) == p

    def test_dashboard_fail(self, exp_with_session, a):
        p = a.participant()
        p2 = a.participant()
        n = a.node()
        n2 = a.node()
        n.fail()
        assert p.failed is False
        assert p2.failed is False
        assert n.failed is True
        assert n2.failed is False
        data = [
            {"id": p.id, "object_type": "Participant"},
            {"id": p2.id, "object_type": "Participant"},
            {"id": n.id, "object_type": "Node"},
            {"id": n2.id, "object_type": "Node"},
        ]
        result = exp_with_session.dashboard_fail(data)
        assert result == {"message": "Failed 1 Nodes, 2 Participants"}
        assert p.failed is True
        assert p2.failed is True
        assert n.failed is True
        assert n2.failed is True

    def test_protected_routes_is_empty_list_by_default(self, exp):
        assert exp.protected_routes == []

    def test_protected_routes_parses_config_value_json(self, active_config, exp):
        active_config.set("protected_routes", '["/info/<int:node_id>/<int:info_id>"]')

        assert exp.protected_routes == ["/info/<int:node_id>/<int:info_id>"]

    def test_normalize_entry_information_calls_recruiter(self, exp):
        with mock.patch(
            "dallinger.recruiters.Recruiter.normalize_entry_information"
        ) as normalizer:
            normalizer.side_effect = lambda *args: {
                "assignment_id": "A",
                "worker_id": "W",
                "hit_id": "H",
                "entry_information": args[-1],
            }
            exp.normalize_entry_information({"foo": "bar"})
            normalizer.assert_called_once_with({"foo": "bar"})

    def test_on_assignment_submitted_to_recruiter__approves_and_records_base_payment(
        self, a, active_config, exp
    ):
        participant = a.participant()
        exp.bonus = mock.Mock(return_value=0.01)
        end_time = datetime(2000, 1, 1)

        exp.on_assignment_submitted_to_recruiter(
            participant=participant,
            event={
                "event_type": "AssignmentSubmitted",
                "participant_id": participant.id,
                "assignment_id": participant.assignment_id,
                "timestamp": end_time,
            },
        )

        assert participant.base_pay == active_config.get("base_payment")
        assert participant.status == "approved"
        assert participant.bonus == 0.01

    def test_on_assignment_submitted_to_recruiter__pays_no_bonus_if_less_than_one_cent(
        self, a, exp
    ):
        participant = a.participant()
        end_time = datetime(2000, 1, 1)

        exp.on_assignment_submitted_to_recruiter(
            participant=participant,
            event={
                "event_type": "AssignmentSubmitted",
                "participant_id": participant.id,
                "assignment_id": participant.assignment_id,
                "timestamp": end_time,
            },
        )

        assert participant.bonus == 0

    def test_on_assignment_submitted_to_recruiter__sets_end_time(self, a, exp):
        participant = a.participant()
        end_time = datetime(2000, 1, 1)

        exp.on_assignment_submitted_to_recruiter(
            participant=participant,
            event={
                "event_type": "AssignmentSubmitted",
                "participant_id": participant.id,
                "assignment_id": participant.assignment_id,
                "timestamp": end_time,
            },
        )

        assert participant.end_time == end_time

    def test_on_assignment_submitted_to_recruiter__noop_if_already_approved_worker(
        self, a, exp
    ):
        participant = a.participant()
        participant.status = "approved"
        end_time = datetime(2000, 1, 1)

        exp.on_assignment_submitted_to_recruiter(
            participant=participant,
            event={
                "event_type": "AssignmentSubmitted",
                "participant_id": participant.id,
                "assignment_id": participant.assignment_id,
                "timestamp": end_time,
            },
        )

        assert participant.base_pay is None

    def test_on_assignment_submitted_to_recruiter__failed_data_check(self, a, exp):
        participant = a.participant()
        exp.data_check = mock.Mock(return_value=False)
        end_time = datetime(2000, 1, 1)

        exp.on_assignment_submitted_to_recruiter(
            participant=participant,
            event={
                "event_type": "AssignmentSubmitted",
                "participant_id": participant.id,
                "assignment_id": participant.assignment_id,
                "timestamp": end_time,
            },
        )

        assert participant.status == "bad_data"

    def test_on_assignment_submitted_to_recruiter__failed_attention_check(self, a, exp):
        participant = a.participant()
        exp.attention_check = mock.Mock(return_value=False)
        end_time = datetime(2000, 1, 1)

        exp.on_assignment_submitted_to_recruiter(
            participant=participant,
            event={
                "event_type": "AssignmentSubmitted",
                "participant_id": participant.id,
                "assignment_id": participant.assignment_id,
                "timestamp": end_time,
            },
        )

        assert participant.status == "did_not_attend"

    def test_participant_task_completed_grants_qualification_for_experiment_id(
        self, exp
    ):
        participant = mock.Mock(spec=Participant, worker_id="some worker id")

        exp.participant_task_completed(participant)

        assert (
            participant.recruiter.assign_experiment_qualifications.call_args_list
            == [
                mock.call(
                    worker_id="some worker id",
                    qualifications=[
                        {
                            "name": "TEST_EXPERIMENT_UID",
                            "description": "Experiment-specific qualification",
                        },
                    ],
                )
            ]
        )

    def test_participant_task_completed_adds_group_qualification_if_group(
        self, active_config, exp
    ):
        active_config.set("group_name", " some-group-1, some-group-2  ")
        participant = mock.Mock(spec=Participant, worker_id="some worker id")

        exp.participant_task_completed(participant)

        assert (
            participant.recruiter.assign_experiment_qualifications.call_args_list
            == [
                mock.call(
                    worker_id="some worker id",
                    qualifications=[
                        {
                            "name": "TEST_EXPERIMENT_UID",
                            "description": "Experiment-specific qualification",
                        },
                        {
                            "name": "some-group-1",
                            "description": "Experiment group qualification",
                        },
                        {
                            "name": "some-group-2",
                            "description": "Experiment group qualification",
                        },
                    ],
                )
            ]
        )

    def test_participant_task_completed_skips_assigning_qualification_if_so_configured(
        self, active_config, exp
    ):
        participant = mock.Mock(spec=Participant, worker_id="some worker id")
        active_config.set("assign_qualifications", False)

        exp.participant_task_completed(participant)

        participant.recruiter.assign_experiment_qualifications.assert_not_called()

    def test_participant_task_completed_skips_assigning_qualification_if_overrecruited(
        self, exp
    ):
        participant = mock.Mock(
            spec=Participant, worker_id="some worker id", status="overrecruited"
        )

        exp.participant_task_completed(participant)

        participant.recruiter.assign_experiment_qualifications.assert_not_called()

    def test_publish_to_subscribers(self, exp):
        with mock.patch("dallinger.db.redis_conn") as mock_redis:
            exp.publish_to_subscribers("A plain message!", "surprise")
            mock_redis.publish.assert_called_once_with("surprise", "A plain message!")

    def test_publish_to_subscribers_no_channel_name(self, exp):
        with mock.patch("dallinger.db.redis_conn") as mock_redis:
            exp.channel = "exp_default"
            exp.publish_to_subscribers("A plain message!")
            mock_redis.publish.assert_called_once_with(
                "exp_default", "A plain message!"
            )

    def test_send_enqueues_worker_function(self, exp):
        from dallinger.db import redis_conn
        from dallinger.experiment_server.worker_events import worker_function

        with mock.patch(
            "dallinger.experiment_server.worker_events.Queue"
        ) as mock_queue_class:
            mock_queue = mock_queue_class.return_value = mock.Mock()
            exp.channel = "exp_default"
            exp.send('exp_default:{"key":"value","sender":1}')
            mock_queue_class.assert_called_once_with("high", connection=redis_conn)
            mock_queue.enqueue.assert_called_once_with(
                worker_function,
                "WebSocketMessage",
                None,
                1,
                node_id=None,
                receive_timestamp=mock.ANY,
                details={
                    "message": '{"key":"value","sender":1}',
                    "channel_name": "exp_default",
                },
                queue_name="high",
            )

    def test_send_non_json_calls_synchronously(self, exp):
        with mock.patch(
            "dallinger.experiment.Experiment.receive_message"
        ) as mock_receive:
            exp.channel = "exp_default"
            exp.send("exp_default:value!")
            mock_receive.assert_called_once_with(
                "value!", channel_name="exp_default", receive_time=mock.ANY
            )

    def test_send_no_participant_calls_synchronously(self, exp):
        # In order to make an async call we need to be able to get a
        # participant_id or a node_id from the message
        with mock.patch(
            "dallinger.experiment.Experiment.receive_message"
        ) as mock_receive:
            exp.channel = "exp_default"
            exp.send('exp_default:{"key":"value"}')
            mock_receive.assert_called_once_with(
                '{"key":"value"}', channel_name="exp_default", receive_time=mock.ANY
            )


class TestTaskRegistration(object):
    def test_deferred_task_decorator(self, tasks_with_cleanup):
        from dallinger.experiment import scheduled_task

        decorator = scheduled_task("interval", minutes=15)
        assert len(tasks_with_cleanup) == 0

        def fake_task():
            pass

        # Decorator does not modify or wrap the function
        assert decorator(fake_task) is fake_task
        assert len(tasks_with_cleanup) == 1
        assert tasks_with_cleanup[0] == {
            "func_name": "fake_task",
            "trigger": "interval",
            "kwargs": (("minutes", 15),),
        }


class TestRouteRegistration(object):
    @pytest.fixture
    def cleared_routes(self):
        from dallinger import experiment

        routes = experiment.EXPERIMENT_ROUTE_REGISTRATIONS
        orig_routes = routes[:]
        routes.clear()
        yield routes
        routes[:] = orig_routes

    def test_deferred_route_decorator(self, cleared_routes):
        from dallinger.experiment import experiment_route

        decorator = experiment_route("/route", methods=["POST", "GET"])
        assert len(cleared_routes) == 0

        def fake_route():
            pass

        # Decorator does not modify or wrap the function
        assert decorator(fake_route) is fake_route
        assert len(cleared_routes) == 1
        assert cleared_routes[0] == {
            "rule": "/route",
            "kwargs": (("methods", ["POST", "GET"]),),
            "func_name": "fake_route",
        }
