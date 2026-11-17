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

logger = logging.getLogger(__name__)


def scan_in_a_thread():
    """Make Werkzeug's stat reloader scan the watched files in a thread of
    gevent's thread pool, rather than in the hub's thread. It reloads on the
    same changes as before. If Werkzeug's reloader isn't as this expects, it
    logs a warning and leaves the reloader as it is."""
    try:
        from werkzeug import _reloader

        _reloader._find_stat_paths
        loop = _reloader.StatReloaderLoop
    except (ImportError, AttributeError):
        logger.warning(
            "Werkzeug's stat reloader has changed, so the development server's "
            "reloader still scans files on the server's own thread."
        )
        return

    def run_step(self):
        mtimes = _in_a_thread(
            _mtimes, _reloader._find_stat_paths, self.extra_files, self.exclude_patterns
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


def _in_a_thread(function, *args):
    """Return ``function(*args)``, run in a thread of gevent's thread pool,
    while the calling greenlet waits and the hub runs the others."""
    import gevent

    return gevent.get_hub().threadpool.apply(function, args)
