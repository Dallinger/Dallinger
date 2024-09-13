# -*- coding: utf-8 -*-
# flake8: noqa

# Vendored copy from git://github.com/reallistic/rq-gevent-worker.git
# because there isn't a working release.

from __future__ import absolute_import, division, print_function, unicode_literals

from gevent import monkey
from gevent.hub import LoopExit

monkey.patch_all()

import logging
import signal

import gevent
import gevent.pool
from rq import Worker
from rq.exceptions import DequeueTimeout
from rq.job import JobStatus
from rq.logutils import setup_loghandlers
from rq.timeouts import BaseDeathPenalty, JobTimeoutException
from rq.version import VERSION
from rq.worker import StopRequested, WorkerStatus, blue, green


class GeventDeathPenalty(BaseDeathPenalty):
    def setup_death_penalty(self):
        exception = JobTimeoutException(
            "Gevent Job exceeded maximum timeout value (%d seconds)." % self._timeout
        )
        self.gevent_timeout = gevent.Timeout(self._timeout, exception)
        self.gevent_timeout.start()

    def cancel_death_penalty(self):
        self.gevent_timeout.cancel()


class GeventWorker(Worker):
    death_penalty_class = GeventDeathPenalty
    DEFAULT_POOL_SIZE = 20

    def __init__(self, *args, **kwargs):
        pool_size = self.DEFAULT_POOL_SIZE
        if "pool_size" in kwargs:
            pool_size = kwargs.pop("pool_size")
        self.gevent_pool = gevent.pool.Pool(pool_size)
        self.children = []
        self.gevent_worker = None
        super(GeventWorker, self).__init__(*args, **kwargs)

    def register_birth(self):
        super(GeventWorker, self).register_birth()
        self.connection.hset(self.key, "pool_size", self.gevent_pool.size)

    def heartbeat(self, timeout=0, pipeline=None):
        connection = pipeline if pipeline is not None else self.connection
        super(GeventWorker, self).heartbeat(timeout)
        connection.hset(self.key, "curr_pool_len", len(self.gevent_pool))

    def _install_signal_handlers(self):
        def request_force_stop():
            self.log.warning("Cold shut down.")
            self.gevent_pool.kill()
            raise SystemExit()

        def request_stop():
            if not self._stop_requested:
                gevent.signal_handler(signal.SIGINT, request_force_stop)
                gevent.signal_handler(signal.SIGTERM, request_force_stop)

                self.log.warning("Warm shut down requested.")
                self.log.warning(
                    "Stopping after all greenlets are finished. "
                    "Press Ctrl+C again for a cold shutdown."
                )

                self._stop_requested = True
                self.gevent_pool.join()
                if self.gevent_worker is not None:
                    self.gevent_worker.kill(StopRequested)

        gevent.signal_handler(signal.SIGINT, request_stop)
        gevent.signal_handler(signal.SIGTERM, request_stop)

    def set_current_job_id(self, job_id, pipeline=None):
        pass

    def _work(self, burst=False, logging_level=logging.INFO):
        """Starts the work loop.

        Pops and performs all jobs on the current list of queues.  When all
        queues are empty, block and wait for new jobs to arrive on any of the
        queues, unless `burst` mode is enabled.

        The return value indicates whether any jobs were processed.
        """
        setup_loghandlers(logging_level)
        self._install_signal_handlers()

        self.did_perform_work = False
        self.register_birth()
        self.log.info(
            "RQ GEVENT worker (Greenlet pool size={0}) {1!r} started, version {2}".format(
                self.gevent_pool.size, self.key, VERSION
            )
        )
        self.set_state(WorkerStatus.STARTED)

        try:
            while True:
                try:
                    self.check_for_suspension(burst)

                    if self.should_run_maintenance_tasks:
                        self.clean_registries()

                    if self._stop_requested:
                        self.log.info("Stopping on request.")
                        break

                    try:
                        worker_ttl = self.worker_ttl
                    except AttributeError:
                        # For back-compatibility with rq < 1.13.0
                        worker_ttl = self.default_worker_ttl

                    timeout = None if burst else max(1, worker_ttl - 60)

                    result = self.dequeue_job_and_maintain_ttl(timeout)
                    if result is None and burst:
                        self.log.info("RQ worker {0!r} done, quitting".format(self.key))

                        try:
                            # Make sure dependented jobs are enqueued.
                            gevent.wait(self.children)
                        except LoopExit:
                            pass
                        result = self.dequeue_job_and_maintain_ttl(timeout)

                    if result is None:
                        break
                except StopRequested:
                    break

                job, queue = result
                self.execute_job(job, queue)

        finally:
            if not self.is_horse:
                self.register_death()
        return self.did_perform_work

    def work(self, burst=False, logging_level=logging.INFO):
        """
        Spawning a greenlet to be able to kill it when it's blocked dequeueing job
        :param burst: if it's burst worker don't need to spawn a greenlet
        """
        # If the is a burst worker it's not needed to spawn greenlet
        if burst:
            return self._work(burst, logging_level=logging_level)

        self.gevent_worker = gevent.spawn(
            self._work, burst, logging_level=logging_level
        )
        self.gevent_worker.join()
        return self.gevent_worker.value

    def execute_job(self, job, queue):
        def job_done(child):
            self.children.remove(child)
            self.did_perform_work = True
            self.heartbeat()
            if job.get_status() == JobStatus.FINISHED:
                queue.enqueue_dependents(job)

        child_greenlet = self.gevent_pool.spawn(self.perform_job, job, queue)
        child_greenlet.link(job_done)
        self.children.append(child_greenlet)

    def dequeue_job_and_maintain_ttl(self, timeout):
        if self._stop_requested:
            raise StopRequested()

        result = None
        while True:
            if self._stop_requested:
                raise StopRequested()

            self.heartbeat()

            if self.gevent_pool.full():
                self.set_state(WorkerStatus.BUSY)
                self.log.warning(
                    "RQ GEVENT worker greenlet pool empty current size %s",
                    self.gevent_pool.size,
                )

            while self.gevent_pool.full():
                gevent.sleep(0.1)
                if self._stop_requested:
                    raise StopRequested()

            try:
                result = self.queue_class.dequeue_any(
                    self.queues, timeout, connection=self.connection
                )
                self.set_state(WorkerStatus.IDLE)
                if result is not None:
                    job, queue = result
                    self.log.info(
                        "%s: %s (%s)"
                        % (green(queue.name), blue(job.description), job.id)
                    )
                break
            except DequeueTimeout:
                pass

        self.heartbeat()
        return result


def main():
    import sys

    from rq.cli import worker as rq_main

    if "-w" in sys.argv or "--worker-class" in sys.argv:
        print(
            "You cannot specify worker class when using this script,"
            "use the official rqworker instead"
        )
        sys.exit(1)

    sys.argv.extend(["-w", "rq_gevent_worker.GeventWorker"])
    rq_main()
