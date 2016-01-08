"""A clock process."""

from apscheduler.schedulers.blocking import BlockingScheduler
from wallace import db, models
from psiturk.models import Participant
session = db.session

scheduler = BlockingScheduler()


@scheduler.scheduled_job('interval', minutes=0.25)
def check_db_for_missing_notifications():
    print("1")
    participants = Participant.query.all()
    print participants
    print("2")
    try:
        nodes = models.Node.query.all()
        print nodes
    except:
        print "something has gone wrong!"
        import traceback
        traceback.print_exc()
    print("3")

scheduler.start()
