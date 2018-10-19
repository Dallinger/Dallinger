"""A clock process."""

from collections import defaultdict
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler

import dallinger
from dallinger import recruiters
from dallinger.models import Participant
from dallinger.utils import ParticipationTime


# Import the experiment.
exp = dallinger.experiment.load()

scheduler = BlockingScheduler()


def run_check(participants, config, reference_time):
    """For each participant, if they've been active for longer than the
    experiment duration + 2 minutes, we take action.
    """
    recruiters_with_late_participants = defaultdict(list)
    for p in participants:
        timeline = ParticipationTime(p, reference_time, config)
        if timeline.is_overdue:
            print(
                "Error: participant {} with status {} has been playing for too "
                "long - their recruiter will be notified.".format(p.id, p.status)
            )
            recruiters_with_late_participants[p.recruiter_id].append(p)

    for recruiter_id, participants in recruiters_with_late_participants.items():
        recruiter = recruiters.by_name(recruiter_id)
        recruiter.notify_duration_exceeded(participants, reference_time)


@scheduler.scheduled_job('interval', minutes=0.5)
def check_db_for_missing_notifications():
    """Check the database for missing notifications."""
    config = dallinger.config.get_config()
    participants = Participant.query.filter_by(status="working").all()
    reference_time = datetime.now()

    run_check(participants, config, reference_time)


def launch():
    config = dallinger.config.get_config()
    if not config.ready:
        config.load()
    scheduler.start()
