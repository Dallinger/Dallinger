"""Each worker keeps its child processes going beside it.

When the experiment has game types, each ``dallinger_heroku_worker`` process
starts a runner as a child process, and starts another each time it exits.
The platform restarts a worker that stops, but not a process the worker
started. A worker that can't load the experiment logs the error and starts no
runner. The worker keeps its CPU workers (``cpu_processes_per_worker``) going
in the same way.

The wait before restarting a child starts at :data:`RESTART_DELAY` seconds
and doubles after each attempt, up to :data:`MAX_RESTART_DELAY`. A child that
ran for at least :data:`MAX_RESTART_DELAY` seconds resets it. So a child that
can't start or keeps crashing is retried, and logged, about once a minute
instead of every second.

When the worker gets ``SIGTERM`` or ``SIGINT``, it sends its children
``SIGTERM`` at once, so the runner gives up its sessions while the worker
finishes its jobs. The worker exits after its children do.
"""

import logging
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

RESTART_DELAY = 1
"""Seconds between a child exiting and the next one starting, at first."""

MAX_RESTART_DELAY = 60
"""Longest wait between children. A child that runs at least this long
resets the wait to :data:`RESTART_DELAY`."""

# Python 3.12's os.fork warns about threads while it still holds its fork
# locks, and Dallinger's warning hook can switch greenlets there. A second
# fork from another greenlet would then block the whole process, so
# supervisors fork one at a time. The lock is created on first use, after
# the worker has monkey-patched threading, so that it is a gevent lock.
_fork_lock = None


def _get_fork_lock():
    global _fork_lock
    if _fork_lock is None:
        _fork_lock = threading.Lock()
    return _fork_lock


class RunnerSupervisor:
    """Run ``command`` in a child process, and run it again after each time
    it exits, until :meth:`stop` is called, waiting between
    :data:`RESTART_DELAY` and :data:`MAX_RESTART_DELAY` seconds as the module
    docstring describes. The child shares the worker's output. ``name``
    describes the child in log messages.
    """

    def __init__(self, command=("dallinger_realtime",), name="real-time runner"):
        self.command = list(command)
        self.name = name
        self.process = None
        self.stopping = threading.Event()
        # Held while starting a child, so stop() can't miss one.
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._supervise, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        """Send the child ``SIGTERM``, and start no more.

        Only the first call sends ``SIGTERM``, though a worker calls it from
        both its signal handler and its cleanup.
        """
        with self.lock:
            if self.stopping.is_set():
                return
            self.stopping.set()
            if self.process is not None:
                self.process.terminate()

    def join(self):
        """Wait for the last child to exit, once :meth:`stop` is called."""
        self.thread.join()

    def _supervise(self):
        delay = RESTART_DELAY
        while True:
            with self.lock:
                if self.stopping.is_set():
                    return
                try:
                    with _get_fork_lock():
                        self.process = subprocess.Popen(self.command)
                    started = time.monotonic()
                except OSError:
                    logger.exception("Couldn't start the %s.", self.name)
                    self.process = None
            if self.process is None:
                reason = "couldn't start"
            else:
                reason = "exited with code {}".format(self.process.wait())
                if time.monotonic() - started >= MAX_RESTART_DELAY:
                    delay = RESTART_DELAY
            if self.stopping.is_set():
                return
            logger.warning(
                "The %s %s. Starting another in %s second(s).",
                self.name,
                reason,
                delay,
            )
            if self.stopping.wait(delay):
                return
            delay = min(delay * 2, MAX_RESTART_DELAY)
