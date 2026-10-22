"""Console logging for the local development server (``dallinger develop debug``).

The development server runs as several processes that share one terminal: the
``flask run`` reloader, the Flask process it restarts on every code change, and
the RQ worker and clock that the Flask process starts. Each process configures
its own logging, so this module gives them one line format::

    13:35:51 web    Experiment launch complete!
    13:35:52 worker WARNING Something worth a look
    13:36:25 web    GET /does-not-exist 404 in 3 ms
    13:36:31 web    POST /participant 200 in 45 ms

The level is shown for warnings and errors only. Text that bypasses logging,
such as the werkzeug debugger's tracebacks or ``print()`` output, is printed
as it is. The same text is written to a terminal and to a pipe or file; only
a terminal gets colour.

The console hides routine records: werkzeug's start-up banner and access log
(replaced by one announcement line and :class:`AccessLogMiddleware`, which
leaves out successful requests for static files, the dashboard and polling;
see :func:`hide_requests`), RQ and APScheduler messages below
WARNING, the "New participant requested:" lines logged while the experiment
launches (the start-up block's participant link replaces them), and most of
APScheduler's warnings that a job run was skipped or missed because the
previous run or the clock was late: none in the 30 seconds from the first
one (the clock warming up), then at most one a minute, with a count of those
hidden. A record logged with a topic (``extra={TOPIC: "name"}``, or a tuple
of names) is hidden if its message is the same as the last one shown for
that topic, so that, for example, "Recruitment closed." is shown once rather
than once for every participant who finishes.
``logs.jsonl`` in the develop directory still receives every record.

If a code change stops the experiment importing, the develop directory's
``app.py`` serves :func:`load_error_app` and logs the error once with
:func:`report_load_error`, so the console keeps this format until the next
change fixes it.

Environment variables:

- ``DALLINGER_DEV_LOG=full`` turns the filtering off, restoring werkzeug's
  banner and its log line for every request (``dallinger develop debug
  --verbose`` sets it).
- ``DALLINGER_DEV_SLOW_REQUEST_SECONDS`` sets how long a hidden request may
  take before it is reported, marked "(slow)" like any other slow request
  (default 1).
- ``NO_COLOR`` and ``FORCE_COLOR`` override the terminal check.

Only the development server uses this module; deployed experiments (gunicorn,
Heroku, Docker) and legacy ``dallinger debug`` keep their logging. Messages
that test harnesses wait for, such as "Experiment launch complete!", "New
participant requested:" and "Recruitment closed.", keep their wording.
"""

import logging
import os
import re
import secrets
import sys
import time
import traceback

from werkzeug.wsgi import ClosingIterator

LOG_MODE_ENV = "DALLINGER_DEV_LOG"
ROLE_ENV = "DALLINGER_DEV_ROLE"
SLOW_REQUEST_ENV = "DALLINGER_DEV_SLOW_REQUEST_SECONDS"
PIN_ENV = "WERKZEUG_DEBUG_PIN"
#: ``extra`` key that gives a record a topic; see :class:`ConsoleFilter`.
TOPIC = "dallinger_console_topic"
_PIN_ANNOUNCED_ENV = "DALLINGER_DEV_PIN_ANNOUNCED"

_DEFAULT_SLOW_REQUEST_SECONDS = 1.0
_ROLE_WIDTH = 6
_QUIET_BELOW_WARNING = ("rq", "apscheduler")
# GeventWorker logs these on every stop; the development server only stops
# its worker on purpose (Ctrl+C or a code reload).
_WORKER_STOP_MESSAGES = {
    "Warm shut down requested.",
    "Stopping after all greenlets are finished. "
    "Press Ctrl+C again for a cold shutdown.",
}
_WERKZEUG_ACCESS_SUFFIX = '"%s" %s %s'
_RUNNING_ON = re.compile(r" \* Running on (\S+://\S+)")
_DETECTED_CHANGE = re.compile(r" \* Detected change in '(.+)', reloading")
_DEBUGGER_PIN = re.compile(r" \* Debugger PIN: [\d-]+")
# APScheduler warns once per job whenever a run overlaps the previous one or
# the clock fell behind: routine while the clock warms up, or after the
# computer slept or a debugger paused it, and a burst of lines each time.
_SCHEDULER_OVERLAP_MESSAGES = (
    "skipped: maximum number of running instances reached",
    "was missed by",
)
_SCHEDULER_WARM_UP_SECONDS = 30
_SCHEDULER_REPEAT_SECONDS = 60

_DIM, _YELLOW, _RED, _RESET = "\x1b[2m", "\x1b[33m", "\x1b[31m", "\x1b[0m"


def full_output_requested():
    """Return True if ``DALLINGER_DEV_LOG=full`` turns filtering off."""
    return os.environ.get(LOG_MODE_ENV, "").strip().lower() == "full"


def use_colour(stream):
    """Return whether to colour text written to ``stream``.

    ``FORCE_COLOR`` (any value but ``0`` or empty) forces colour on, and
    ``NO_COLOR`` or ``TERM=dumb`` turn it off. Otherwise colour is used only
    when ``stream`` is a terminal.
    """
    force = os.environ.get("FORCE_COLOR", "")
    if force and force != "0":
        return True
    if "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


class ConsoleFormatter(logging.Formatter):
    """Format records as ``HH:MM:SS <role> [LEVEL ]message``.

    Parameters
    ----------
    role : str
        Process name shown on every line, such as ``web``, ``worker`` or
        ``clock``.
    colour : bool
        Dim the time and role, and colour warnings, errors and failed
        requests.
    """

    def __init__(self, role, colour=False):
        super().__init__()
        self.role = role
        self.colour = colour

    def format(self, record):
        message = getattr(record, "dallinger_console_message", None)
        if message is None:
            message = record.getMessage()
        message = message.rstrip("\n")
        if record.levelno >= logging.WARNING:
            message = f"{record.levelname} {message}"
        if record.exc_info:
            record.exc_text = record.exc_text or self.formatException(record.exc_info)
        if record.exc_text:
            message = f"{message}\n{record.exc_text}"
        if record.stack_info:
            message = f"{message}\n{self.formatStack(record.stack_info)}"

        prefix = "{} {} ".format(
            time.strftime("%H:%M:%S", time.localtime(record.created)),
            self.role.ljust(_ROLE_WIDTH),
        )
        if not self.colour:
            return prefix + message
        status = getattr(record, "dallinger_status", 0)
        if record.levelno >= logging.ERROR or status >= 500:
            message = f"{_RED}{message}{_RESET}"
        elif record.levelno >= logging.WARNING or status >= 400:
            message = f"{_YELLOW}{message}{_RESET}"
        return f"{_DIM}{prefix}{_RESET}{message}"


class ConsoleFilter(logging.Filter):
    """Hide routine and repeated records from the console and shorten werkzeug's.

    A record with a :data:`TOPIC` attribute is hidden if its message is the
    same as that of the last record shown for the topic. The attribute may
    also be a tuple of topics: the record is then hidden only if its message
    is the last shown for each of them, and is the last shown for all of
    them once shown, so that it ends repeats in each. Warnings and errors
    are always shown. Each server process keeps its own record, so a line
    may be shown once more after an auto-reload.

    Records are never modified: a shortened werkzeug message is stored as
    ``record.dallinger_console_message``, which :class:`ConsoleFormatter`
    prints instead, so other handlers still see the original.

    Parameters
    ----------
    server_details : str, optional
        Text such as ``auto-reload on, debugger PIN 123-456-789`` added to
        the "Development server on <url>" line that replaces werkzeug's
        start-up banner.
    """

    def __init__(self, server_details=None):
        super().__init__()
        self.server_details = server_details
        self._overlaps_started = None
        self._overlap_shown_at = None
        self._overlaps_hidden = 0
        self._last_message_by_topic = {}

    def filter(self, record):
        if full_output_requested():
            return True
        if record.levelno < logging.WARNING:
            if record.name.split(".")[0] in _QUIET_BELOW_WARNING:
                return False
        elif record.name == "rq.worker" and record.msg in _WORKER_STOP_MESSAGES:
            return False
        elif record.name.startswith("apscheduler.") and any(
            text in str(record.msg) for text in _SCHEDULER_OVERLAP_MESSAGES
        ):
            return self._filter_scheduler_overlap(record)
        if record.name == "werkzeug":
            return self._filter_werkzeug(record)
        if _is_launch_recruitment(record):
            return False
        topics = getattr(record, TOPIC, None)
        if topics and record.levelno < logging.WARNING:
            topics = (topics,) if isinstance(topics, str) else tuple(topics)
            message = record.getMessage()
            if all(self._last_message_by_topic.get(t) == message for t in topics):
                return False
            self._last_message_by_topic.update(dict.fromkeys(topics, message))
        return True

    def _filter_scheduler_overlap(self, record):
        """Hide the first 30 seconds of overlap warnings, then show one a minute.

        The window starts at the first warning rather than when logging is set
        up, because the clock may wait for Redis before its scheduler starts.
        """
        now = time.monotonic()
        if self._overlaps_started is None:
            self._overlaps_started = now
        if now - self._overlaps_started < _SCHEDULER_WARM_UP_SECONDS or (
            self._overlap_shown_at is not None
            and now - self._overlap_shown_at < _SCHEDULER_REPEAT_SECONDS
        ):
            self._overlaps_hidden += 1
            return False
        if self._overlaps_hidden:
            record.dallinger_console_message = (
                f"{record.getMessage()} ({self._overlaps_hidden} similar scheduler "
                "warnings not shown; they are shown at most once a minute)"
            )
        self._overlap_shown_at = now
        self._overlaps_hidden = 0
        return True

    def _filter_werkzeug(self, record):
        if not isinstance(record.msg, str):
            return True
        if record.msg.rstrip().endswith(_WERKZEUG_ACCESS_SUFFIX):
            return False
        message = record.getMessage()
        urls = _RUNNING_ON.findall(message)
        if urls:
            if "debugger PIN " in (self.server_details or ""):
                # Werkzeug starts the serving process after this line, so it
                # inherits this and can hide werkzeug's own PIN line.
                os.environ[_PIN_ANNOUNCED_ENV] = "1"
            details = f" ({self.server_details})" if self.server_details else ""
            record.dallinger_console_message = (
                f"Development server on {', '.join(urls)}{details}"
            )
            return True
        change = _DETECTED_CHANGE.match(message)
        if change:
            record.dallinger_console_message = (
                f"Reloading: {_display_path(change.group(1))} changed"
            )
            return True
        if "Press CTRL+C to quit" in message or message.startswith(
            " * Restarting with "
        ):
            return False
        if os.environ.get(_PIN_ANNOUNCED_ENV) and (
            message == " * Debugger is active!" or _DEBUGGER_PIN.fullmatch(message)
        ):
            return False
        return True


def _is_launch_recruitment(record):
    """Return True for a "New participant requested:" record logged by ``/launch``.

    ``dallinger develop debug`` prints the participant link when the launch
    finishes, so the console shows only later requests.
    """
    from flask import has_request_context, request

    from dallinger.recruiters import NEW_RECRUIT_LOG_PREFIX

    return (
        isinstance(record.msg, str)
        and record.msg.startswith(NEW_RECRUIT_LOG_PREFIX)
        and has_request_context()
        and request.path == "/launch"
    )


def _display_path(path):
    """Return ``path`` relative to the working directory if it is inside it.

    The develop directory links to the experiment's files, and werkzeug may
    report a change under either name, so a file reached through one of the
    directory's links is shown by its name there too.
    """
    relative = os.path.relpath(path)
    if not relative.startswith(".."):
        return relative
    real = os.path.realpath(path)
    with os.scandir(".") as entries:
        links = [entry for entry in entries if entry.is_symlink()]
    for entry in links:
        target = os.path.realpath(entry.path)
        if real == target:
            return entry.name
        if real.startswith(target + os.sep):
            return os.path.join(entry.name, os.path.relpath(real, target))
    return path


def configure_console_logging(role, level=logging.INFO):
    """Replace the root logger's console handler with the development format.

    File handlers, such as the ``logs.jsonl`` handler, are kept and keep
    receiving every record that reaches them, including records from loggers
    set to a lower level than the root logger. The console only shows
    records at ``level`` or above, unless ``DALLINGER_DEV_LOG=full``.

    Parameters
    ----------
    role : str
        Process name shown on every line (``web``, ``worker`` or ``clock``).
    level : int
        Level of the root logger and of the console.

    Returns
    -------
    logging.Handler
        The new console handler.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        if type(handler) is logging.StreamHandler:
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(ConsoleFormatter(role, colour=use_colour(sys.stderr)))
    handler.addFilter(ConsoleFilter())
    handler.setLevel(logging.NOTSET if full_output_requested() else level)
    root.addHandler(handler)
    root.setLevel(level)
    return handler


def configure_from_environment(level=logging.INFO):
    """Configure console logging if the development server started this process.

    The development server sets ``DALLINGER_DEV_ROLE`` for the worker and
    clock processes it starts.

    Parameters
    ----------
    level : int
        Level of the root logger.

    Returns
    -------
    bool
        True if logging was configured.
    """
    role = os.environ.get(ROLE_ENV)
    if not role:
        return False
    configure_console_logging(role, level=level)
    return True


def slow_request_seconds():
    """Return the duration after which a successful request is reported."""
    value = os.environ.get(SLOW_REQUEST_ENV)
    if not value:
        return _DEFAULT_SLOW_REQUEST_SECONDS
    try:
        return float(value)
    except ValueError:
        logging.getLogger(__name__).warning(
            "Ignoring %s=%r, which isn't a number of seconds.", SLOW_REQUEST_ENV, value
        )
        return _DEFAULT_SLOW_REQUEST_SECONDS


def hide_requests(*prefixes):
    """Hide successful requests for paths starting with any of ``prefixes``.

    The development server's console shows one line per request, except for
    static files, the dashboard and background polling, which would drown
    out the pages participants take. Packages built on Dallinger call this
    for their own asset and polling routes. Failed and slow requests are
    still shown.

    Parameters
    ----------
    *prefixes : str
        Path prefixes, such as ``"/static/"`` or ``"/log/"``.
    """
    _HIDDEN_PATH_PREFIXES.update(prefixes)


_HIDDEN_PATH_PREFIXES = {
    "/static/",
    "/favicon.ico",
    "/robots.txt",
    "/dashboard",
    "/logs/",
    "/launch",
    "/health",
    "/summary",
    "/presence",
    "/experiment/",
    "/experiment_property/",
    "/tracking_event/",
}


class AccessLogMiddleware:
    """Log requests, with their status and duration.

    Each request is logged to the ``dallinger.access`` logger, at INFO,
    except successful requests for paths passed to :func:`hide_requests`
    (static files, the dashboard and polling) that take less than
    ``slow_seconds``, and successful WebSocket requests, which last as long
    as their connection. The path is logged without its query string. The
    duration runs until the response has been sent.

    Parameters
    ----------
    app : callable
        The WSGI application to wrap.
    slow_seconds : float, optional
        Report hidden requests that take at least this long, and mark any
        request that does as slow. Defaults to
        :func:`slow_request_seconds`.
    """

    logger = logging.getLogger("dallinger.access")

    def __init__(self, app, slow_seconds=None):
        self.app = app
        self.slow_seconds = (
            slow_request_seconds() if slow_seconds is None else slow_seconds
        )

    def __call__(self, environ, start_response):
        started = time.monotonic()
        status = []

        def start_response_and_record(status_line, headers, exc_info=None):
            status[:] = [int(status_line.split(None, 1)[0])]
            return start_response(status_line, headers, exc_info)

        try:
            response = self.app(environ, start_response_and_record)
        except Exception:
            self._log(environ, 500, started)
            raise
        return ClosingIterator(
            response,
            lambda: self._log(environ, status[0] if status else 500, started),
        )

    def _log(self, environ, status, started):
        seconds = time.monotonic() - started
        if status < 400 and environ.get("HTTP_UPGRADE", "").lower() == "websocket":
            # A WebSocket request lasts as long as its connection.
            return
        path = environ.get("PATH_INFO", "") or "/"
        slow = status < 400 and seconds >= self.slow_seconds
        if status < 400 and not slow and path.startswith(tuple(_HIDDEN_PATH_PREFIXES)):
            return
        duration = f"{seconds:.1f} s" if seconds >= 1 else f"{seconds * 1000:.0f} ms"
        self.logger.info(
            "%s %s %s in %s%s",
            environ.get("REQUEST_METHOD", "-"),
            path,
            status,
            duration,
            " (slow)" if slow else "",
            extra={"dallinger_status": status},
        )


def setup_dev_server(app):
    """Set up logging in a ``flask run`` process of the development server.

    Called by the develop directory's ``app.py`` in both the reloader process
    and the process that serves requests. Configures the console format,
    logs requests, and replaces werkzeug's start-up banner
    and debugger lines with one "Development server on <url>" line that
    includes the debugger PIN. Unless ``WERKZEUG_DEBUG_PIN`` is already set,
    the PIN is chosen at random once per session, so it stays the same
    across reloads. With ``DALLINGER_DEV_LOG=full``, only the line format is
    set up: werkzeug's banner, PIN and request lines are left as they are.

    Parameters
    ----------
    app : flask.Flask
        The experiment server's Flask application.
    """
    handler = configure_console_logging("web")
    if full_output_requested():
        return
    app.wsgi_app = AccessLogMiddleware(app.wsgi_app)

    from werkzeug.serving import is_running_from_reloader

    if is_running_from_reloader():
        return
    reload, debugger = _flask_run_settings()
    details = [f"auto-reload {'on' if reload else 'off'}"]
    if debugger:
        from werkzeug.debug import get_pin_and_cookie_name

        # Werkzeug derives its PIN from the machine's MAC address, which some
        # systems randomise per process, so its PIN can change on every
        # reload. Choosing one here keeps it the same for the session.
        os.environ.setdefault(PIN_ENV, _random_pin())
        pin = get_pin_and_cookie_name(app)[0]
        details.append(f"debugger PIN {pin}" if pin else "debugger PIN disabled")
    for log_filter in handler.filters:
        log_filter.server_details = ", ".join(details)
    _hide_flask_banner()


def load_error_app(error):
    """Return a Flask app to serve while the experiment fails to import.

    Used by the develop directory's ``app.py`` after a code change, so that
    the error is reported once (see :func:`report_load_error`) and the server
    keeps running until the next change fixes it. Every request gets a short
    500 page instead of the traceback again.

    Parameters
    ----------
    error : Exception
        The exception raised while importing the experiment.
    """
    from flask import Flask

    summary = "".join(traceback.format_exception_only(error)).strip()
    message = (
        f"The experiment failed to load: {summary}\n"
        "Fix it and save: the server reloads automatically. The traceback is "
        "in the server's output.\n"
    )
    app = Flask(__name__)

    @app.route("/", defaults={"path": ""}, methods=["GET", "POST"])
    @app.route("/<path:path>", methods=["GET", "POST"])
    def experiment_failed_to_load(path):
        return message, 500, {"Content-Type": "text/plain; charset=utf-8"}

    return app


def report_load_error(error):
    """Log the error that stopped the experiment loading, with its traceback.

    Parameters
    ----------
    error : Exception
        The exception raised while importing the experiment.
    """
    logging.getLogger("dallinger.dev_server").error(
        "The experiment failed to load. Fix the error and save: the server "
        "reloads automatically.",
        exc_info=error,
    )


def _random_pin():
    """Return a random debugger PIN in werkzeug's ``123-456-789`` format."""
    digits = f"{secrets.randbelow(10**9):09d}"
    return "-".join((digits[:3], digits[3:6], digits[6:]))


def _flask_run_settings():
    """Return ``(reload, debugger)`` for the running ``flask run`` command.

    Flask resolves unset ``--reload`` and ``--debugger`` options from its
    debug flag after loading the app, so this does the same.
    """
    import click
    from flask.helpers import get_debug_flag

    ctx = click.get_current_context(silent=True)
    params = ctx.params if ctx is not None else {}
    debug = get_debug_flag()
    reload = params.get("reload")
    debugger = params.get("debugger")
    return (
        debug if reload is None else reload,
        debug if debugger is None else debugger,
    )


def _hide_flask_banner():
    """Stop ``flask run`` printing "Serving Flask app" and "Debug mode".

    Flask prints these with ``click.echo`` after loading the app, so they
    can't be filtered as log records.
    """
    import flask.cli

    if hasattr(flask.cli, "show_server_banner"):
        flask.cli.show_server_banner = lambda *args, **kwargs: None
