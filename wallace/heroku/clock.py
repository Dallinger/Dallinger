"""A clock process."""

from apscheduler.schedulers.blocking import BlockingScheduler

scheduler = BlockingScheduler()


@scheduler.scheduled_job('interval', minutes=0.25)
def print_log_statement():
    """Print a log statement every so often."""
    print("Clock process logging statement.")

scheduler.start()
