#!/usr/bin/python
# -*- coding: utf-8 -*-
import os
import mock
import pytest
import dallinger.db
import datetime
from dallinger.config import get_config
from dallinger.heroku import app_name
from dallinger.models import Participant


@pytest.fixture
def setup():
    db = dallinger.db.init_db(drop_all=True)
    os.chdir('tests/experiment')
    config = get_config()
    if not config.ready:
        config.load_config()
    yield config
    db.rollback()
    db.close()
    os.chdir('../..')


class TestHeroku(object):

    def test_heroku_app_name(self):
        id = "8fbe62f5-2e33-4274-8aeb-40fc3dd621a0"
        assert(len(app_name(id)) < 30)


class TestHerokuClock(object):

    class a(object):

        @staticmethod
        def participant(**kwargs):
            defaults = {
                'worker_id': '1',
                'hit_id': '1',
                'assignment_id': '1',
                'mode': 'test',
            }
            defaults.update(kwargs)
            part = Participant(**defaults)
            part.creation_time = datetime.datetime.now()

            return part

    def test_check_db_for_missing_notifications_assembles_resources(self, setup):
        # Can't import until after config is loaded:
        from dallinger.heroku.clock import check_db_for_missing_notifications
        with mock.patch.multiple('dallinger.heroku.clock',
                                 run_check=mock.DEFAULT,
                                 MTurkConnection=mock.DEFAULT) as mocks:
            mocks['MTurkConnection'].return_value = 'fake connection'
            check_db_for_missing_notifications()

            mocks['run_check'].assert_called()

    def test_run_check_does_nothing_if_assignment_still_current(self, setup):
        from dallinger.heroku.clock import run_check
        config = {'duration': 1.0}
        mturk = mock.Mock(**{'get_assignment.return_value': ['fake']})
        participants = [self.a.participant()]
        session = None
        reference_time = datetime.datetime.now()
        run_check(config, mturk, participants, session, reference_time)

        mturk.get_assignment.assert_not_called()

    def test_run_check_sets_participant_status_if_mturk_reports_approved(self, setup):
        from dallinger.heroku.clock import run_check
        config = {'duration': 1.0}
        fake_assignment = mock.Mock(AssignmentStatus='Approved')
        mturk = mock.Mock(**{'get_assignment.return_value': [fake_assignment]})
        participants = [self.a.participant()]
        session = mock.Mock()
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        run_check(config, mturk, participants, session, reference_time)

        assert participants[0].status == 'approved'
        session.commit.assert_called()

    def test_run_check_sets_participant_status_if_mturk_reports_rejected(self, setup):
        from dallinger.heroku.clock import run_check
        config = {'duration': 1.0}
        fake_assignment = mock.Mock(AssignmentStatus='Rejected')
        mturk = mock.Mock(**{'get_assignment.return_value': [fake_assignment]})
        participants = [self.a.participant()]
        session = mock.Mock()
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        run_check(config, mturk, participants, session, reference_time)

        assert participants[0].status == 'rejected'
        session.commit.assert_called()

    def test_run_check_resubmits_notification_if_mturk_reports_submitted(self, setup):
        from dallinger.heroku.clock import run_check
        # Include whimsical set to True to avoid error in the False code branch:
        config = {
            'duration': 1.0,
            'host': 'fakehost.herokuapp.com',
            'whimsical': True
        }
        fake_assignment = mock.Mock(AssignmentStatus='Submitted')
        mturk = mock.Mock(**{'get_assignment.return_value': [fake_assignment]})
        participants = [self.a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        with mock.patch('dallinger.heroku.clock.requests') as mock_requests:
            run_check(config, mturk, participants, session, reference_time)

            mock_requests.post.assert_called_once_with(
                'http://fakehost.herokuapp.com/notifications',
                data={
                    'Event.1.EventType': 'AssignmentSubmitted',
                    'Event.1.AssignmentId': participants[0].assignment_id
                }
            )

    def test_run_check_builds_non_whimsical_email_message_without_error(self, setup):
        from dallinger.heroku.clock import run_check
        # Include whimsical set to True to avoid error in the False code branch:
        config = {
            'duration': 1.0,
            'host': 'fakehost.herokuapp.com',
            'whimsical': False
        }
        fake_assignment = mock.Mock(AssignmentStatus='Submitted')
        mturk = mock.Mock(**{'get_assignment.return_value': [fake_assignment]})
        participants = [self.a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        with mock.patch('dallinger.heroku.clock.requests'):
            run_check(config, mturk, participants, session, reference_time)

    def test_run_check_shuts_hit_down_if_mturk_doesnt_have_assignment(self, setup):
        from dallinger.heroku.clock import run_check
        # Include whimsical set to True to avoid error in the False code branch:
        config = {
            'duration': 1.0,
            'host': 'fakehost.herokuapp.com',
            'whimsical': True
        }
        mturk = mock.Mock(**{'get_assignment.return_value': []})
        participants = [self.a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        os_env_email = None
        os_env_password = None
        with mock.patch('dallinger.heroku.clock.requests') as mock_requests:
            run_check(config, mturk, participants, session, reference_time)

            mock_requests.patch.assert_called_once_with(
                'https://api.heroku.com/apps/fakehost/config-vars',
                data='{"auto_recruit": "false"}',
                auth=(os_env_email, os_env_password),
                headers={
                    "Accept": "application/vnd.heroku+json; version=3",
                    "Content-Type": "application/json"
                }
            )

            mock_requests.post.assert_called_once_with(
                'http://fakehost.herokuapp.com/notifications',
                data={
                    'Event.1.EventType': 'NotificationMissing',
                    'Event.1.AssignmentId': participants[0].assignment_id
                }
            )

    def test_run_check_no_assignement_builds_non_whimsical_email_message_without_error(self, setup):
        from dallinger.heroku.clock import run_check
        # Include whimsical set to True to avoid error in the False code branch:
        config = {
            'duration': 1.0,
            'host': 'fakehost.herokuapp.com',
            'whimsical': False
        }
        mturk = mock.Mock(**{'get_assignment.return_value': []})
        participants = [self.a.participant()]
        session = None
        # Move the clock forward so assignment is overdue:
        reference_time = datetime.datetime.now() + datetime.timedelta(hours=6)
        with mock.patch('dallinger.heroku.clock.requests'):
            run_check(config, mturk, participants, session, reference_time)
