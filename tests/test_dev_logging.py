import io
import logging
import re
import sys

import pytest
from werkzeug.serving import WSGIRequestHandler
from werkzeug.test import Client

from dallinger.dev_logging import (
    AccessLogMiddleware,
    ConsoleFilter,
    ConsoleFormatter,
    configure_from_environment,
    load_error_app,
    report_load_error,
    use_colour,
)


def record(name="dallinger", level=logging.INFO, msg="hello", args=(), exc=None):
    return logging.LogRecord(name, level, __file__, 1, msg, args, exc)


def console_lines(records, server_details=None):
    """Return what the console shows for ``records``."""
    log_filter = ConsoleFilter(server_details)
    formatter = ConsoleFormatter("web")
    return [formatter.format(r) for r in records if log_filter.filter(r)]


def test_lines_show_time_and_role_and_level_from_warning_up():
    formatter = ConsoleFormatter("worker")
    assert re.fullmatch(r"\d\d:\d\d:\d\d worker hello", formatter.format(record()))
    warning = formatter.format(record(level=logging.WARNING, msg="careful"))
    assert warning.endswith(" worker WARNING careful")


def test_tracebacks_are_kept_in_full():
    try:
        raise ValueError("boom")
    except ValueError:
        exc = sys.exc_info()
    text = ConsoleFormatter("clock").format(
        record(level=logging.ERROR, msg="Job failed", exc=exc)
    )
    assert " clock  ERROR Job failed\nTraceback (most recent call last):" in text
    assert text.endswith("ValueError: boom")


def test_colour_only_when_requested():
    failed = record(msg="GET /boom 500 in 3 ms")
    failed.dallinger_status = 500
    assert "\x1b[" not in ConsoleFormatter("web").format(failed)
    assert "\x1b[31mGET /boom 500" in ConsoleFormatter("web", colour=True).format(
        failed
    )


@pytest.mark.parametrize(
    "env, tty, expected",
    [
        ({}, True, True),
        ({}, False, False),
        ({"NO_COLOR": "1"}, True, False),
        ({"TERM": "dumb"}, True, False),
        ({"FORCE_COLOR": "1"}, False, True),
    ],
)
def test_use_colour(monkeypatch, env, tty, expected):
    for name in ("NO_COLOR", "FORCE_COLOR", "TERM"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    stream = io.StringIO()
    stream.isatty = lambda: tty
    assert use_colour(stream) is expected


ACCESS = '127.0.0.1 - - [21/Oct/2026 13:36:21] "%s" %s %s'
ROUTINE = [
    record("werkzeug", msg=ACCESS, args=("GET /timeline HTTP/1.1", "200", "-")),
    record("werkzeug", msg=ACCESS, args=("GET /missing HTTP/1.1", "404", "-")),
    record("werkzeug", msg="Press CTRL+C to quit"),
    record("werkzeug", msg=" * Restarting with stat"),
    record("apscheduler.scheduler", msg="Scheduler started"),
    record("rq.worker", level=logging.WARNING, msg="Warm shut down requested."),
]
KEPT = [
    record("psynet", msg="Experiment launch complete!"),
    record("dallinger.recruiters", msg="New participant requested: http://x/ad"),
    record("dallinger.recruiters", msg="Recruitment closed."),
    record("apscheduler.executors.default", level=logging.ERROR, msg="Job failed"),
    record("rq.worker", level=logging.WARNING, msg="Cold shut down."),
    record("werkzeug", level=logging.ERROR, msg="code 400, message Bad request"),
]


def test_routine_records_are_hidden_and_others_kept():
    lines = console_lines(ROUTINE + KEPT)
    assert len(lines) == len(KEPT)
    assert lines[0].endswith("Experiment launch complete!")


def test_launch_recruitment_links_are_hidden_but_later_ones_kept():
    import flask

    new_recruit = record("dallinger.recruiters", msg="New participant requested: x")
    app = flask.Flask(__name__)
    with app.test_request_context("/launch"):
        assert console_lines([new_recruit]) == []
    with app.test_request_context("/worker_complete"):
        assert len(console_lines([new_recruit])) == 1


def test_full_mode_keeps_everything(monkeypatch):
    monkeypatch.setenv("DALLINGER_DEV_LOG", "full")
    assert len(console_lines(ROUTINE + KEPT)) == len(ROUTINE + KEPT)


def test_werkzeug_banner_becomes_one_line_without_changing_the_record(monkeypatch):
    monkeypatch.setenv("DALLINGER_DEV_PIN_ANNOUNCED", "")
    pin = record("werkzeug", msg=" * Debugger PIN: %s", args=("123-456-789",))
    assert console_lines([pin]), "werkzeug's PIN line is shown until announced"
    banner = record(
        "werkzeug",
        msg="WARNING: This is a development server.\n"
        " * Running on http://127.0.0.1:5000",
    )
    reload = record(
        "werkzeug", msg=" * Detected change in '/elsewhere/experiment.py', reloading"
    )
    lines = console_lines([banner, reload, pin], "auto-reload on, debugger PIN 123")
    assert len(lines) == 2
    assert lines[0].endswith(
        "web    Development server on http://127.0.0.1:5000 "
        "(auto-reload on, debugger PIN 123)"
    )
    assert lines[1].endswith("web    Reloading: /elsewhere/experiment.py changed")
    assert banner.getMessage().startswith("WARNING: This is a development server.")


def test_a_reload_through_a_linked_file_shows_its_name_here(tmp_path, monkeypatch):
    experiment = tmp_path / "experiment" / "experiment.py"
    experiment.parent.mkdir()
    experiment.write_text("")
    develop = tmp_path / "develop"
    develop.mkdir()
    (develop / "experiment.py").symlink_to(experiment)
    monkeypatch.chdir(develop)
    reload = record("werkzeug", msg=f" * Detected change in '{experiment}', reloading")
    assert console_lines([reload])[0].endswith("Reloading: experiment.py changed")


def test_an_experiment_that_fails_to_load_gets_a_short_500_page():
    try:
        compile("def broken(:", "experiment.py", "exec")
    except SyntaxError as error:
        app = load_error_app(error)
    response = Client(app).get("/timeline?unique_id=1")
    assert response.status_code == 500
    assert "The experiment failed to load: " in response.text
    assert "SyntaxError" in response.text


def test_a_load_error_is_logged_once_with_its_traceback(caplog):
    error = SyntaxError("invalid syntax")
    with caplog.at_level(logging.ERROR):
        report_load_error(error)
    (logged,) = caplog.records
    assert logged.getMessage().startswith("The experiment failed to load.")
    assert logged.exc_info[1] is error


def test_scheduler_overlap_warnings_are_collapsed(monkeypatch):
    now = [0.0]
    monkeypatch.setattr("dallinger.dev_logging.time.monotonic", lambda: now[0])
    log_filter = ConsoleFilter()

    def shown(
        at,
        msg='Execution of job "%s" skipped: maximum number of running '
        "instances reached (%d)",
    ):
        now[0] = at
        overlap = record("apscheduler.scheduler", logging.WARNING, msg, ("job", 1))
        if not log_filter.filter(overlap):
            return None
        return getattr(overlap, "dallinger_console_message", overlap.getMessage())

    assert shown(5) is None and shown(34) is None, "hidden while warming up"
    assert shown(36).endswith(
        "(2 similar scheduler warnings not shown; they are shown at most once a minute)"
    )
    assert shown(45, 'Run time of job "%s" was missed by %s') is None
    assert shown(97) is not None
    assert log_filter.filter(
        record("apscheduler.executors.default", logging.ERROR, "Job failed")
    )


def test_announced_debugger_lines_are_hidden_unless_unsecured(monkeypatch):
    monkeypatch.setenv("DALLINGER_DEV_PIN_ANNOUNCED", "1")
    lines = console_lines(
        [
            record("werkzeug", level=logging.WARNING, msg=" * Debugger is active!"),
            record("werkzeug", msg=" * Debugger PIN: %s", args=("123-456-789",)),
            record(
                "werkzeug",
                level=logging.WARNING,
                msg=" * Debugger PIN disabled. DEBUGGER UNSECURED!",
            ),
        ]
    )
    assert len(lines) == 1
    assert lines[0].endswith("WARNING  * Debugger PIN disabled. DEBUGGER UNSECURED!")


def test_werkzeug_access_records_are_hidden(caplog):
    class Handler(WSGIRequestHandler):
        def __init__(self):
            self.client_address = ("127.0.0.1", 1)
            self.requestline = "GET / HTTP/1.1"

    caplog.set_level(logging.INFO, logger="werkzeug")
    Handler().log_request(200)
    assert caplog.records
    assert console_lines(caplog.records) == []


def test_development_role_sets_up_the_console(monkeypatch, capsys):
    monkeypatch.delenv("DALLINGER_DEV_ROLE", raising=False)
    assert configure_from_environment() is False

    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    monkeypatch.setenv("DALLINGER_DEV_ROLE", "clock")
    try:
        assert configure_from_environment(logging.WARNING) is True
        logging.getLogger("dallinger.test").info("hidden")
        logging.getLogger("dallinger.test").warning("job overran")
    finally:
        root.handlers[:] = handlers
        root.setLevel(level)
    err = capsys.readouterr().err
    assert re.search(r"^\d\d:\d\d:\d\d clock  WARNING job overran$", err, re.M)
    assert "hidden" not in err


def wsgi_app(environ, start_response):
    path = environ["PATH_INFO"]
    if path == "/boom":
        raise ValueError("boom")
    start_response("404 NOT FOUND" if path == "/missing" else "200 OK", [])
    return [b"body"]


def test_access_log_reports_failed_and_slow_requests_only(caplog):
    caplog.set_level(logging.INFO, logger="dallinger.access")
    client = Client(AccessLogMiddleware(wsgi_app, slow_seconds=60))
    client.get("/fine", buffered=True)
    client.get("/missing?assignmentId=abc", buffered=True)
    with pytest.raises(ValueError):
        client.get("/boom")
    slow = Client(AccessLogMiddleware(wsgi_app, slow_seconds=0))
    slow.get("/slow", buffered=True)
    slow.get("/chat", headers={"Upgrade": "websocket"}, buffered=True)
    slow.get("/missing", headers={"Upgrade": "websocket"}, buffered=True)

    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 4
    assert re.fullmatch(r"GET /missing 404 in \d+ ms", messages[0])
    assert re.fullmatch(r"GET /boom 500 in \d+ ms", messages[1])
    assert re.fullmatch(r"GET /slow 200 in \d+ ms \(slow\)", messages[2])
    assert messages[3].startswith("GET /missing 404")
