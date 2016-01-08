"""A clock process."""

from apscheduler.schedulers.blocking import BlockingScheduler
from wallace import db, models
from psiturk.models import Participant
import imp
import inspect
session = db.session

scheduler = BlockingScheduler()

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

exp = experiment(session)


@scheduler.scheduled_job('interval', minutes=0.25)
def check_db_for_missing_notifications():
    print("1")
    participants = Participant.query.all()
    print participants
    print("2")
    nodes = models.Node.query.all()
    print nodes
    print("3")

scheduler.start()
