"""A clock process."""

from datetime import datetime
import json

from apscheduler.schedulers.blocking import BlockingScheduler
from boto.mturk.connection import MTurkConnection
import requests

import dallinger
from dallinger import db
from dallinger.models import Participant
from dallinger.heroku.messages import NullHITMessager

# Import the experiment.
experiment = dallinger.experiment.load()

session = db.session

scheduler = BlockingScheduler()
config = dallinger.config.get_config()


def run_check(config, mturk, participants, session, reference_time):

    # get experiment duration in seconds
    duration_seconds = config.get('duration') * 60.0 * 60.0

    # for each participant, if they've been active for longer than the
    # experiment duration + 5 minutes, we take action.
    for p in participants:
        time_active = (reference_time - p.creation_time).total_seconds()

        if time_active > (duration_seconds + 120):
            print ("Error: participant {} with status {} has been playing for too "
                   "long and no notification has arrived - "
                   "running emergency code".format(p.id, p.status))

            # get their assignment
            assignment_id = p.assignment_id

            # ask amazon for the status of the assignment
            try:
                assignment = mturk.get_assignment(assignment_id)[0]
                status = assignment.AssignmentStatus
            except:
                status = None
            print "assignment status from AWS is {}".format(status)
            hit_id = p.hit_id
            # Use a null handler for now since Gmail is blocking outgoing email
            # from random servers:
            messager = NullHITMessager(
                when=reference_time,
                assignment_id=assignment_id,
                hit_duration=duration_seconds,
                time_active=time_active,
                config=config
            )

            if status == "Approved":
                # if its been approved, set the status accordingly
                print "status set to approved"
                p.status = "approved"
                session.commit()
            elif status == "Rejected":
                print "status set to rejected"
                # if its been rejected, set the status accordingly
                p.status = "rejected"
                session.commit()
            elif status == "Submitted":
                # if it has been submitted then resend a submitted notification
                args = {
                    'Event.1.EventType': 'AssignmentSubmitted',
                    'Event.1.AssignmentId': assignment_id
                }
                requests.post(
                    "http://" + config.get('host') + '/notifications',
                    data=args)

                # message the researcher:
                messager.send_resubmitted_msg()

                print ("Error - submitted notification for participant {} missed. "
                       "Database automatically corrected, but proceed with caution."
                       .format(p.id))
            else:
                # if it has not been submitted shut everything down
                # first turn off autorecruit
                host = config.get('host')
                host = host[:-len(".herokuapp.com")]
                args = json.dumps({"auto_recruit": "false"})
                headers = {
                    "Accept": "application/vnd.heroku+json; version=3",
                    "Content-Type": "application/json",
                    "Authorization": "Bearer {}".format(
                        config.get("heroku_auth_token"))
                }
                requests.patch(
                    "https://api.heroku.com/apps/{}/config-vars".format(host),
                    data=args,
                    headers=headers,
                )

                # then force expire the hit via boto
                mturk.expire_hit(hit_id)

                # message the researcher
                messager.send_hit_cancelled_msg()

                # send a notificationmissing notification
                args = {
                    'Event.1.EventType': 'NotificationMissing',
                    'Event.1.AssignmentId': assignment_id
                }
                requests.post(
                    "http://" + config.get('host') + '/notifications',
                    data=args)

                print ("Error - abandoned/returned notification for participant {} missed. "
                       "Experiment shut down. Please check database and then manually "
                       "resume experiment."
                       .format(p.id))


@scheduler.scheduled_job('interval', minutes=0.5)
def check_db_for_missing_notifications():
    """Check the database for missing notifications."""
    aws_access_key_id = config.get('aws_access_key_id')
    aws_secret_access_key = config.get('aws_secret_access_key')
    host_by_sandbox_setting = {
        "debug": 'mechanicalturk.sandbox.amazonaws.com',
        "sandbox": 'mechanicalturk.sandbox.amazonaws.com',
        "live": 'mechanicalturk.amazonaws.com'
    }
    mturk = MTurkConnection(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        host=host_by_sandbox_setting[config.get('mode')])

    # get all participants with status < 100
    participants = Participant.query.filter_by(status="working").all()
    reference_time = datetime.now()

    run_check(config, mturk, participants, session, reference_time)


def launch():
    if not config.ready:
        config.load()
    scheduler.start()


if __name__ == '__main__':
    launch()
