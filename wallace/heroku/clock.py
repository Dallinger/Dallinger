"""A clock process."""

from apscheduler.schedulers.blocking import BlockingScheduler
from wallace import db, models
import imp
import inspect
from psiturk.models import Participant

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
