"""A clock process."""

from datetime import datetime
from email.mime.text import MIMEText
import json
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from boto.mturk.connection import MTurkConnection
import requests

import dallinger
from dallinger import db
from dallinger.models import Participant

from dallinger import config

# Import the experiment.
experiment = dallinger.experiments.load()

session = db.session

scheduler = BlockingScheduler()

# create a connection to MTurk
aws_access_key_id = os.environ['aws_access_key_id']
aws_secret_access_key = os.environ['aws_secret_access_key']
if config.getboolean('Shell Parameters', 'launch_in_sandbox_mode'):
    conn = MTurkConnection(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        host='mechanicalturk.sandbox.amazonaws.com')
else:
    conn = MTurkConnection(
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key)


@scheduler.scheduled_job('interval', minutes=0.5)
def check_database():
    """Run automated checks over the database."""
    check_for_missed_notifications()


def set_autorecruit(autorecruit):
    """Set the autorecruit config var."""
    host = os.environ['HOST']
    host = host[:-len(".herokuapp.com")]
    if autorecruit:
        args = json.dumps({"auto_recruit": "true"})
    else:
        args = json.dumps({"auto_recruit": "false"})
    headers = {
        "Accept": "application/vnd.heroku+json; version=3",
        "Content-Type": "application/json"
    }
    heroku_email_address = os.getenv('heroku_email_address')
    heroku_password = os.getenv('heroku_password')
    requests.patch(
        "https://api.heroku.com/apps/{}/config-vars".format(host),
        data=args,
        auth=(heroku_email_address, heroku_password),
        headers=headers)


def expire_hit():
    hit_id = Participant.query.get(1).hit_id
    conn.expire_hit(hit_id)


def check_for_missed_notifications():
    """Check the database for missing notifications."""
    # get all working participants
    participants = Participant.query.filter_by(status="working").all()

    # get current time
    current_time = datetime.now()

    # get experiment duration in seconds
    duration = float(config.get('HIT Configuration', 'duration')) * 60 * 60

    # for each participant, if current_time - start_time > duration + 5 mins
    for p in participants:
        p_time = (current_time - p.creation_time).total_seconds()

        if p_time > (duration + 120):
            print ("Error: participant {} with status {} has been playing for too "
                   "long and no notification has arrived - "
                   "running emergency code".format(p.id, p.status))

            # get their assignment
            assignment_id = p.assignment_id

            # ask amazon for the status of the assignment
            try:
                assignment = conn.get_assignment(assignment_id)[0]
                status = assignment.AssignmentStatus
            except:
                status = None
            print "assignment status from AWS is {}".format(status)
            hit_id = p.hit_id

            if status in ["Approved", "Rejected"]:
                # if its been approved/rejected, set the status accordingly
                print "status set to {}".format(status)
                p.status = status.lower()
                session.commit()
            elif status == "Submitted":
                # if it has been submitted then resend a submitted notification
                args = {
                    'Event.1.EventType': 'AssignmentSubmitted',
                    'Event.1.AssignmentId': assignment_id
                }
                requests.post(
                    "http://" + os.environ['HOST'] + '/notifications',
                    data=args)

                print ("Error - submitted notification for participant {} missed. "
                       "Database automatically corrected, but proceed with caution."
                       .format(p.id))
            else:
                # if it has not been submitted shut everything down
                # first turn off autorecruit
                set_autorecruit(False)

                # then force expire the hit
                expire_hit()

                # send a notificationmissing notification
                args = {
                    'Event.1.EventType': 'NotificationMissing',
                    'Event.1.AssignmentId': assignment_id
                }
                requests.post(
                    "http://" + os.environ['HOST'] + '/notifications',
                    data=args)

                print ("Error - abandoned/returned notification for participant {} missed. "
                       "Experiment shut down. Please check database and then manually "
                       "resume experiment."
                       .format(p.id))


scheduler.start()
