"""Each worker keeps its child processes going beside it.

When the experiment has game types, each ``dallinger_heroku_worker`` process
starts a runner as a child process, and starts another :data:`RESTART_DELAY`
seconds after each time it exits. The platform restarts a worker that stops,
but not a process the worker started. A worker that can't load the experiment
logs the error and starts no runner. The worker keeps its CPU workers
(``cpu_processes_per_worker``) going in the same way.

When the worker gets ``SIGTERM`` or ``SIGINT``, it sends its children
``SIGTERM`` at once, so the runner gives up its sessions while the worker
finishes its jobs. The worker exits after its children do.
"""

import logging
import subprocess
import threading

logger = logging.getLogger(__name__)

RESTART_DELAY = 1
"""Seconds between a child exiting and the next one starting."""

# Python 3.12's os.fork warns about threads while it still holds its fork
# locks, and Dallinger's warning hook can switch greenlets there. A second
# fork from another greenlet would then block the whole process, so
# supervisors fork one at a time.
_fork_lock = threading.Lock()


class RunnerSupervisor:
    """Run ``command`` in a child process, and run it again
    :data:`RESTART_DELAY` seconds after each time it exits, until :meth:`stop`
    is called. The child shares the worker's output. ``name`` describes the
    child in log messages.
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

        Only the first call sends ``SIGTERM``: a second one would make a CPU
        worker abandon its job.
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
        while True:
            with self.lock:
                if self.stopping.is_set():
                    return
                try:
                    with _fork_lock:
                        self.process = subprocess.Popen(self.command)
                except OSError:
                    logger.exception("Couldn't start the %s.", self.name)
                    self.process = None
            if self.process is None:
                reason = "couldn't start"
            else:
                reason = "exited with code {}".format(self.process.wait())
            if self.stopping.is_set():
                return
            logger.warning(
                "The %s %s. Starting another in %s second(s).",
                self.name,
                reason,
                RESTART_DELAY,
            )
            if self.stopping.wait(RESTART_DELAY):
                return
