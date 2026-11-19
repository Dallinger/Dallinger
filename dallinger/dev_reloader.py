"""Keep the development server's reloader from pausing the server.

``dallinger develop debug`` runs ``flask run``, whose reloader checks every
watched file for changes about once a second. The server is monkey-patched
by gevent, so it runs everything on one hub, and Werkzeug's stat reloader
does its scan in the hub's own thread. While it scans, nothing else runs: no
request, and no real-time view relayed to a page. A real-time game that sends
many views a second, such as one that ticks, then reaches its pages late and
in bursts, so other players' movement stalls or jumps.

:func:`scan_in_a_thread` makes the reloader do its scan in a thread of
gevent's thread pool, a real thread, so the hub keeps serving while it runs.
"""

import logging
import os

import gevent

logger = logging.getLogger(__name__)


def scan_in_a_thread():
    """Run the stat reloader's scan in gevent's thread pool; warn and leave
    it unchanged if Werkzeug's internals differ."""
    try:
        from werkzeug import _reloader
    except ImportError:
        _reloader = None
    loop = getattr(_reloader, "StatReloaderLoop", None)
    if not (hasattr(_reloader, "_find_stat_paths") and hasattr(loop, "run_step")):
        logger.warning(
            "Werkzeug's stat reloader has changed, so the development server's "
            "reloader still scans files on the server's own thread."
        )
        return

    def run_step(self):
        mtimes = gevent.get_hub().threadpool.apply(
            _mtimes,
            (_reloader._find_stat_paths, self.extra_files, self.exclude_patterns),
        )
        # As Werkzeug's own run_step, on the hub's thread, since
        # trigger_reload exits the process.
        for name, mtime in mtimes.items():
            old_time = self.mtimes.get(name)
            if old_time is None:
                self.mtimes[name] = mtime
            elif mtime > old_time:
                self.trigger_reload(name)

    loop.run_step = run_step


def _mtimes(find_paths, extra_files, exclude_patterns):
    """Return the modification time of each watched file."""
    mtimes = {}
    for name in find_paths(extra_files, exclude_patterns):
        try:
            mtimes[name] = os.stat(name).st_mtime
        except OSError:
            continue
    return mtimes
