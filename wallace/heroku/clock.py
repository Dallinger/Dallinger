"""A clock process."""

from apscheduler.schedulers.blocking import BlockingScheduler
from wallace import db
import os
import imp
import inspect
from psiturk.models import Participant
from datetime import datetime
from psiturk.psiturk_config import PsiturkConfig
from boto.mturk.connection import MTurkConnection
import requests
import smtplib
from email.mime.text import MIMEText
import json

config = PsiturkConfig()
config.load_config()

# Specify the experiment.
try:
    exp = imp.load_source('experiment', "wallace_experiment.py")
    classes = inspect.getmembers(exp, inspect.isclass)
    exps = [c for c in classes
            if (c[1].__bases__[0].__name__ in "Experiment")]
    this_experiment = exps[0][0]
    mod = __import__('wallace_experiment', fromlist=[this_experiment])
    experiment = getattr(mod, this_experiment)
except ImportError:
    print "Error: Could not import experiment."
session = db.session

aws_access_key_id = config.get('AWS Access', 'aws_access_key_id')
aws_secret_access_key = config.get('AWS Access', 'aws_secret_access_key')
conn = MTurkConnection(aws_access_key_id, aws_secret_access_key)

scheduler = BlockingScheduler()


@scheduler.scheduled_job('interval', minutes=0.25)
def check_db_for_missing_notifications():
    # get all participants with status < 100
    participants = Participant.query.all()
    participants = [p for p in participants if p.status < 100]

    # get current time
    current_time = datetime.now()

    # get experiment duration in seconds
    duration = float(config.get('HIT Configuration', 'duration'))*60*60

    # for each participant, if current_time - start_time > duration + 5 mins
    emergency = False
    for p in participants:
        p_time = (current_time - p.beginhit).total_seconds
        if p_time > (duration + 300):
            emergency = True
            print "participant {} has been playing for too long and no notification has arrived - running emergency code".format(p)

            # get their assignment
            assignment_id = p.assignmentid

            # ask amazon for the status of the assignment
            try:
                assignment = conn.get_assignment(assignment_id)
                status = assignment.Assignment.AssignmentStatus
            except:
                import traceback
                traceback.print_exc()
            print "assignment status from AWS is {}".format(status)

            if status in ["Submitted", "Approved", "Rejected"]:
                # if it has been submitted then resend a submitted notification
                args = {
                    'Event.1.EventType': 'AssignmentSubmitted',
                    'Event.1.AssignmentId': assignment_id
                }
                requests.post("http://" + os.environ['HOST'] + '/notifications', data=args)
                # send the researcher an email to let them know
                username = os.getenv('wallace_email_username')
                fromaddr = username + "@gmail.com"
                email_password = os.getenv("wallace_email_key")
                toaddr = config.get('HIT Configuration', 'contact_email_on_error')

                msg = MIMEText("Dearest Friend,\n\nI am writing to let you know that at {}, during my regular (and thoroughly enjoyable) \
perousal of the most charming participant data table, I happened to notice that assignment \
{} has been taking longer than we were expecting. I recall you had suggested {} minutes as an upper limit \
for what was an acceptable length of time for each assignement, however this assignment had been underway \
for a shocking {} minutes, a full {} minutes over your allowance. I immediately dispatched a \
telegram to our mutual friends at AWS and they were able to assure me that although the notification \
had failed to be correctly processed, the assignment had in fact been completed. Rather than trouble you, \
I dealt with this myself and I can assure you there is no immediate cause for concern. \
Nonetheless, for my own peace of mind, I would appreciate you taking the time to look into this matter \
at your earliest convenience.\n\nI remain your faithful and obedient servant,\nAlfred R. Wallace\n\nP.S. Please do not respond to this message, \
I am busy with other matters.".format(datetime.now(), assignment_id, round(duration/60), round(p_time/60), round((p_time-duration)/60)))
                msg['Subject'] = "A matter of minor concern."

                server = smtplib.SMTP('smtp.gmail.com:587')
                server.starttls()
                server.login(username, email_password)
                server.sendmail(fromaddr, toaddr, msg.as_string())
                server.quit()
            else:
                # if it has not been submitted shut everything down
                # first turn off autorecruit
                host = os.environ['HOST']
                host = host[:-len(".herokuapp.com")]
                args = json.dumps({"auto_recruit": "false"})
                headers = {
                    "Accept": "application/vnd.heroku+json; version=3",
                    "Content-Type": "application/json"
                }
                heroku_email_address = os.getenv('heroku_email_address')
                heroku_password = os.getenv('heroku_password')
                requests.patch("https://api.heroku.com/apps/{}/config-vars".format(host),
                               data=args,
                               auth=(heroku_email_address, heroku_password),
                               headers=headers)
                # then force expire the hit via boto

                # and send the researcher an email to let them know

    if emergency is False:
        print "No evidence of missing notifications :-)"

scheduler.start()
