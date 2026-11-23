"""The RQ worker that ``dallinger_heroku_worker --cpu`` runs.

A CPU worker runs jobs from the CPU queues one at a time, each in a process
it forks for that job. That is how RQ enforces a job's ``job_timeout`` even
while the job computes without waiting on the network or the database: the
job's process gets ``SIGALRM`` when the timeout expires, and the worker kills
it if it is still running 60 seconds later. A gevent worker can't stop such a
job, because its timeouts fire only when the job yields. So, unlike
``rq_gevent_worker``, this module doesn't monkey-patch, and the worker and
its jobs don't use gevent.

A CPU worker shares its dyno or container with the ordinary worker that
started it, and on shutdown it and its job's process can get ``SIGTERM``
more than once: Heroku sends it to every process, and the ordinary worker
passes it on. So the first ``SIGTERM`` or ``SIGINT`` makes the worker stop
after the running job, it ignores later ones, and the job's process ignores
both.
"""

import signal

from rq.worker import Worker, signal_name

from dallinger import db


class CPUWorker(Worker):
    def __init__(self, *args, startup_watchdog=None, **kwargs):
        self.startup_watchdog = startup_watchdog
        super().__init__(*args, **kwargs)

    def register_birth(self):
        super().register_birth()
        if self.startup_watchdog is not None:
            self.startup_watchdog.kill(block=False)

    def subscribe(self):
        """Start no thread for RQ's worker commands: a fork while another
        thread holds a lock can deadlock the job's process."""

    def request_force_stop(self, signum, frame):
        self.log.debug(
            "Worker %s: ignoring %s, stopping after the running job",
            self.name,
            signal_name(signum),
        )

    def setup_work_horse_signals(self):
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)

    def main_work_horse(self, job, queue):
        # The job's process must not use the worker's database connections.
        db.engine.dispose(close=False)
        super().main_work_horse(job, queue)
