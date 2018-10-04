"""A clock process."""

from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

import dallinger
from dallinger import db
from dallinger.models import Participant
from dallinger.mturk import MTurkService
from dallinger.heroku.messages import HITSummary
from dallinger.heroku.messages import get_messenger
from dallinger.heroku.messages import MessengerError
from dallinger import recruiters


# Import the experiment.
experiment = dallinger.experiment.load()

session = db.session

scheduler = BlockingScheduler()


def run_check(config, mturk, participants, session, reference_time):

    # get experiment duration in seconds
    duration_seconds = config.get('duration') * 60.0 * 60.0

    # Track HITs somehow... TBD.
    hits_to_be_cancelled = set()
    # for each participant, if they've been active for longer than the
    # experiment duration + 5 minutes, we take action.
    for p in participants:
        time_active = (reference_time - p.creation_time).total_seconds()

        if time_active > (duration_seconds + 120):
            print(
                "Error: participant {} with status {} has been playing for too "
                "long - checking in with their recruiter.".format(p.id, p.status)
            )

            recruiter = recruiters.by_name(p.recruiter_id)
            summary = HITSummary(
                assignment_id=p.assignment_id,
                duration=duration_seconds,
                time_active=time_active,
                app_id=config.get('id', 'unknown'),
                when=reference_time,
            )

            recruiter.notify_duration_exceeded(p, summary)

    for hit in hits_to_be_cancelled:
        # Do something to cancel HITs
        recruiter = recruiter.by_name(hit['recruiter_id'])
        recruiter.close_recruitment(hit['id'])
        recruiter.terminate_hit(hit['id'])
        messenger = get_messenger(hit['summary'], config)
        try:
            messenger.send_hit_cancelled_msg()
        except MessengerError as ex:
            print(ex)


@scheduler.scheduled_job('interval', minutes=0.5)
def check_db_for_missing_notifications():
    """Check the database for missing notifications."""
    config = dallinger.config.get_config()
    mturk = MTurkService(
        aws_access_key_id=config.get('aws_access_key_id'),
        aws_secret_access_key=config.get('aws_secret_access_key'),
        region_name=config.get('aws_region'),
        sandbox=config.get('mode') in ('debug', 'sandbox')
    )
    # get all participants with status < 100
    participants = Participant.query.filter_by(status="working").all()
    reference_time = datetime.now()

    run_check(config, mturk, participants, session, reference_time)


def launch():
    config = dallinger.config.get_config()
    if not config.ready:
        config.load()
    scheduler.start()


if __name__ == '__main__':
    launch()
