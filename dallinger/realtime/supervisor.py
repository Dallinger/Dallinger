"""Each worker keeps a runner going beside it.

When the experiment has game types, each ``dallinger_heroku_worker`` process
starts a runner as a child process, and starts another :data:`RESTART_DELAY`
seconds after each time it exits. The platform restarts a worker that stops,
but not a process the worker started. A worker that can't load the experiment
logs the error and starts no runner.

When the worker gets ``SIGTERM`` or ``SIGINT``, it sends its runner
``SIGTERM`` at once, so the runner gives up its sessions while the worker
finishes its jobs. The worker exits after its runner does.
"""

import logging
import subprocess
import threading

logger = logging.getLogger(__name__)

RESTART_DELAY = 1
"""Seconds between a runner exiting and the next one starting."""


class RunnerSupervisor:
    """Run ``command`` in a child process, and run it again
    :data:`RESTART_DELAY` seconds after each time it exits, until :meth:`stop`
    is called. The child shares the worker's output.
    """

    def __init__(self, command=("dallinger_realtime",)):
        self.command = list(command)
        self.process = None
        self.stopping = threading.Event()
        # Held while starting a child, so stop() can't miss one.
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._supervise, daemon=True)

    def start(self):
        self.thread.start()

    def stop(self):
        """Send the runner ``SIGTERM``, and start no more."""
        with self.lock:
            self.stopping.set()
            if self.process is not None:
                self.process.terminate()

    def join(self):
        """Wait for the last runner to exit, once :meth:`stop` is called."""
        self.thread.join()

    def _supervise(self):
        while True:
            with self.lock:
                if self.stopping.is_set():
                    return
                try:
                    self.process = subprocess.Popen(self.command)
                except OSError:
                    logger.exception("Couldn't start the real-time runner.")
                    self.process = None
            if self.process is None:
                reason = "couldn't start"
            else:
                reason = "exited with code {}".format(self.process.wait())
            if self.stopping.is_set():
                return
            logger.warning(
                "The real-time runner %s. Starting another in %s second(s).",
                reason,
                RESTART_DELAY,
            )
            if self.stopping.wait(RESTART_DELAY):
                return
