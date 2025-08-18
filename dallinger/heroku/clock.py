"""A clock process."""

from collections import defaultdict
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import text

import dallinger
from dallinger import db, recruiters
from dallinger.experiment import EXPERIMENT_TASK_REGISTRATIONS
from dallinger.models import Participant
from dallinger.utils import ParticipationTime

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


@scheduler.scheduled_job("interval", minutes=0.5)
def check_db_for_missing_notifications():
    """Check the database for missing notifications."""
    config = dallinger.config.get_config()
    reference_time = datetime.now()
    with db.sessions_scope() as session:
        participants = session.query(Participant).filter_by(status="working").all()
        run_check(participants, config, reference_time)


@scheduler.scheduled_job("interval", seconds=10)
def warn_on_idle_transactions():
    """Warn if any DB sessions are idle in transaction for > 1 second."""
    with db.engine.connect() as conn:
        result = conn.execute(
            text(
                """
            SELECT pid, state, xact_start, query, now() - xact_start AS idle_time
            FROM pg_stat_activity
            WHERE state = 'idle in transaction'
              AND xact_start IS NOT NULL
              AND now() - xact_start > interval '1 second'
        """
            )
        )
        for row in result:
            print(
                f"Session idle in transaction! pid={row.pid}, "
                f"idle_time={row.idle_time}, last_query={row.query}"
            )


@scheduler.scheduled_job("interval", minutes=0.5)
def async_recruiter_status_check():
    """Ask recruiters to check the status of their participants"""

    q = db.get_queue()
    q.enqueue(recruiters.run_status_check)


def launch():
    dallinger.config.get_config(load=True)

    # Import the experiment.
    experiment_class = dallinger.experiment.load()

    for args in EXPERIMENT_TASK_REGISTRATIONS:
        meth_name = args.pop("func_name")
        task = getattr(experiment_class, meth_name, None)
        if task is not None:
            # Give the task's ORM session cleanup and error safety:
            scoped_task = db.scoped_session_decorator(task)
            scheduler.add_job(
                scoped_task,
                trigger=args["trigger"],
                replace_existing=True,
                **dict(args["kwargs"]),
            )

    scheduler.start()
