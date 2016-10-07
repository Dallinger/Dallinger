"""A clock process."""

from datetime import datetime
from email.mime.text import MIMEText
import json
import os

from apscheduler.schedulers.blocking import BlockingScheduler
from boto.mturk.connection import MTurkConnection
from psiturk.psiturk_config import PsiturkConfig
import requests

from dallinger import db
from dallinger.models import Participant

config = PsiturkConfig()
config.load_config()

# Import the experiment.
experiment = dallinger.experiments.load()

session = db.session

scheduler = BlockingScheduler()


@scheduler.scheduled_job('interval', minutes=0.5)
def check_db_for_missing_notifications():
    """Check the database for missing notifications."""
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

    # get all participants with status < 100
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

            # general email settings:
            username = os.getenv('dallinger_email_username')
            fromaddr = username + "@gmail.com"
            email_password = os.getenv("dallinger_email_key")
            toaddr = config.get('HIT Configuration', 'contact_email_on_error')
            whimsical = os.getenv("whimsical")

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
                    "http://" + os.environ['HOST'] + '/notifications',
                    data=args)

                # send the researcher an email to let them know
                if whimsical:
                    msg = MIMEText(
                        """Dearest Friend,\n\nI am writing to let you know that at
 {}, during my regular (and thoroughly enjoyable) perousal of the most charming
  participant data table, I happened to notice that assignment {} has been
 taking longer than we were expecting. I recall you had suggested {} minutes as
 an upper limit for what was an acceptable length of time for each assignement
 , however this assignment had been underway for a shocking {} minutes, a full
 {} minutes over your allowance. I immediately dispatched a telegram to our
 mutual friends at AWS and they were able to assure me that although the
 notification had failed to be correctly processed, the assignment had in fact
 been completed. Rather than trouble you, I dealt with this myself and I can
 assure you there is no immediate cause for concern. Nonetheless, for my own
 peace of mind, I would appreciate you taking the time to look into this matter
 at your earliest convenience.\n\nI remain your faithful and obedient servant,
\nWilliam H. Dallinger\n\n P.S. Please do not respond to this message, I am busy
 with other matters.""".format(
                        datetime.now(),
                        assignment_id,
                        round(duration/60),
                        round(p_time/60),
                        round((p_time-duration)/60)))
                    msg['Subject'] = "A matter of minor concern."
                else:
                    msg = MIMEText(
                        """Dear experimenter,\n\nThis is an automated email from
 Dallinger. You are receiving this email because the Dallinger platform has
 discovered evidence that a notification from Amazon Web Services failed to
 arrive at the server. Dallinger has automatically contacted AWS and has
 determined the dropped notification was a submitted notification (i.e. the
 participant has finished the experiment). This is a non-fatal error and so
 Dallinger has auto-corrected the problem. Nonetheless you may wish to check the
 database.\n\nBest,\nThe Dallinger dev. team.\n\n Error details:\nAssignment: {}
\nAllowed time: {}\nTime since participant started: {}""").format(
                        assignment_id,
                        round(duration/60),
                        round(p_time/60))
                    msg['Subject'] = "Dallinger automated email - minor error."

                # This method commented out as gmail now blocks emails from
                # new locations
                # server = smtplib.SMTP('smtp.gmail.com:587')
                # server.starttls()
                # server.login(username, email_password)
                # server.sendmail(fromaddr, toaddr, msg.as_string())
                # server.quit()
                print ("Error - submitted notification for participant {} missed. "
                       "Database automatically corrected, but proceed with caution."
                       .format(p.id))
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
                requests.patch(
                    "https://api.heroku.com/apps/{}/config-vars".format(host),
                    data=args,
                    auth=(heroku_email_address, heroku_password),
                    headers=headers)

                # then force expire the hit via boto
                conn.expire_hit(hit_id)

                # send the researcher an email to let them know
                if whimsical:
                    msg = MIMEText(
                        """Dearest Friend,\n\nI am afraid I write to you with most
 grave tidings. At {}, during a routine check of the usually most delightful
 participant data table, I happened to notice that assignment {} has been
 taking longer than we were expecting. I recall you had suggested {} minutes as
 an upper limit for what was an acceptable length of time for each assignment,
 however this assignment had been underway for a shocking {} minutes, a full {}
 minutes over your allowance. I immediately dispatched a telegram to our mutual
 friends at AWS and they infact informed me that they had already sent us a
 notification which we must have failed to process, implying that the
 assignment had not been successfully completed. Of course when the seriousness
 of this scenario dawned on me I had to depend on my trusting walking stick for
 support: without the notification I didn't know to remove the old assignment's
 data from the tables and AWS will have already sent their replacement, meaning
 that the tables may already be in a most unsound state!\n\nI am sorry to
 trouble you with this, however, I do not know how to proceed so rather than
 trying to remedy the scenario myself, I have instead temporarily ceased
 operations by expiring the HIT with the fellows at AWS and have refrained from
 posting any further invitations myself. Once you see fit I would be most
 appreciative if you could attend to this issue with the caution, sensitivity
 and intelligence for which I know you so well.\n\nI remain your faithful and
 obedient servant,\nWilliam H. Dallinger\n\nP.S. Please do not respond to this
 message, I am busy with other matters.""".format(
                        datetime.now(),
                        assignment_id,
                        round(duration/60),
                        round(p_time/60),
                        round((p_time-duration)/60)))
                    msg['Subject'] = "Most troubling news."
                else:
                    msg = MIMEText(
                        """Dear experimenter,\n\nThis is an automated email from
 Dallinger. You are receiving this email because the Dallinger platform has
 discovered evidence that a notification from Amazon Web Services failed to
 arrive at the server. Dallinger has automatically contacted AWS and has
 determined the dropped notification was an abandoned/returned notification
 (i.e. the participant had returned the experiment or had run out of time).
 This is a serious error and so Dallinger has paused the experiment - expiring
 the HIT on MTurk and setting auto_recruit to false. Participants currently
 playing will be able to finish, however no further participants will be
 recruited until you do so manually. We strongly suggest you use the details
 below to check the database to make sure the missing notification has not caused
 additional problems before resuming.\nIf you are receiving a lot of these
 emails this suggests something is wrong with your experiment code.\n\nBest,
\nThe Dallinger dev. team.\n\n Error details:\nAssignment: {}
\nAllowed time: {}\nTime since participant started: {}""").format(
                        assignment_id,
                        round(duration/60),
                        round(p_time/60))
                    msg['Subject'] = "Dallinger automated email - major error."

                # This method commented out as gmail now blocks emails from
                # new locations
                # server = smtplib.SMTP('smtp.gmail.com:587')
                # server.starttls()
                # server.login(username, email_password)
                # server.sendmail(fromaddr, toaddr, msg.as_string())
                # server.quit()

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
