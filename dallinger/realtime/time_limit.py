"""The time limit on game code in a pass.

The limit uses ``SIGALRM`` and ``ITIMER_REAL``, so it only works in the main
thread, and only one limit can run in a process at a time.
"""

import logging
import os
import signal
import threading
import time
from contextlib import contextmanager
from functools import partial

logger = logging.getLogger(__name__)


class TimeLimitExceeded(BaseException):
    """Raised in game code that runs past the session's time limit.

    It isn't an :class:`Exception`, so game code that catches every
    ``Exception`` doesn't catch it.
    """


#: How long the timer keeps raising in game code that catches its exception
#: and carries on, as a multiple of the time limit, before it ends the process.
#: Only a loop that catches every exception gets that far, and nothing in the
#: process can stop it.
GIVE_UP_AFTER = 2

# While game code runs past its limit, the timer raises again at this interval.
_REPEAT = 0.05

# While a time limit is running: the message to raise, and the clock time to
# give up at. The signal handler can only find it here.
_running = None


@contextmanager
def time_limits(seconds):
    """Yield a function that returns a new budget of ``seconds``, or an
    unlimited budget if ``seconds`` is ``None``.
    """
    if seconds is None:
        yield _Unlimited
        return
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("A time limit only works in the main thread.")
    previous = signal.signal(signal.SIGALRM, _time_out)
    try:
        yield partial(_Budget, seconds)
    finally:
        signal.signal(signal.SIGALRM, previous)


class _Budget:
    """Runs the game's methods, giving them ``seconds`` in total."""

    def __init__(self, seconds):
        self.seconds = seconds
        self.remaining = seconds

    def run(self, what, method, *args):
        global _running
        message = "{} was running when the session used up its {} seconds.".format(
            what, self.seconds
        )
        if self.remaining <= 0:
            raise TimeLimitExceeded(message)
        started = time.monotonic()
        give_up = started + self.remaining + (GIVE_UP_AFTER - 1) * self.seconds
        _running = (message, give_up)
        signal.setitimer(signal.ITIMER_REAL, self.remaining, _REPEAT)
        try:
            result = method(*args)
        finally:
            _stop_timer()
            self.remaining -= time.monotonic() - started
        return result


class _Unlimited:
    def run(self, what, method, *args):
        return method(*args)


def _stop_timer():
    global _running
    while True:
        # A signal that arrives before the timer stops raises in here.
        try:
            signal.setitimer(signal.ITIMER_REAL, 0)
            _running = None
            return
        except TimeLimitExceeded:
            pass


def _time_out(signum, frame):
    if _running is None:
        return
    message, give_up = _running
    if time.monotonic() >= give_up:
        logger.critical(
            "%s It caught every exception, so the runner is exiting.", message
        )
        os._exit(1)
    raise TimeLimitExceeded(message)
