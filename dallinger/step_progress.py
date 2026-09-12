"""A live checklist for multi-step command line operations such as deployment.

Why this module exists
----------------------
A deploy is a fixed sequence of slow remote steps. Printing one line per
step leaves the operator watching a dead terminal during the slow ones, and
giving each step its own spinner means several libraries compete for the
same cursor. This module gives the whole operation a single live region: a
panel of the declared steps, with a spinner on the step being worked on and
a tick once it succeeds.

Design constraints for maintainers
----------------------------------
- **One owner of the terminal.** A terminal has one cursor, so at most one
  :class:`StepProgress` may be live per process. While one is live,
  :func:`active_steps` returns it, and anything else that would animate
  (the launch wait bar, ``yaspin`` spinners) must report through it with
  :meth:`StepProgress.set_detail` instead of drawing on its own.
- **Ownership is taken, not assumed.** Diverting ``sys.stdout`` only
  redirects code that writes through Python; child processes inherit the
  file descriptors and would draw straight over the panel. So the panel
  takes descriptors 1 and 2 as well (:class:`_FdCapture`) and re-points log
  handlers that hold the terminal. Everything a run produces therefore
  arrives in one place, whoever wrote it.
- **Steps are declared up front.** The operator should see what is still
  coming. A step that turns out to be unnecessary is marked skipped rather
  than removed, so the list never reflows while it is on screen.
- **Diverted output is shown, not discarded.** Captured lines become the
  running step's detail, so a slow step still reports progress. The full
  text goes to a log file whose path is printed when the run ends, and a
  failed step replays its own output below the panel. Facts worth copying,
  such as URLs and passwords, are printed by the caller through
  :meth:`StepProgress.add_epilogue` after the panel closes.
- **Non-interactive output stays a log.** Without a terminal there is no
  live region and nothing is captured: each step start and outcome prints
  one plain line, and other output appears between them, so CI logs and
  redirected output keep the same information in order.
"""

import io
import logging
import os
import re
import sys
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass

from rich import box
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

PENDING = "pending"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
SKIPPED = "skipped"

_ICONS = {
    PENDING: ("○", "dim"),
    DONE: ("✓", "green"),
    FAILED: ("✗", "red"),
    SKIPPED: ("–", "dim"),
}

_LABEL_STYLES = {
    PENDING: "dim",
    RUNNING: "bold",
    DONE: "",
    FAILED: "red",
    SKIPPED: "dim",
}

_PLAIN_PREFIXES = {
    RUNNING: "→",
    DONE: "✓",
    FAILED: "✗",
    SKIPPED: "–",
}

#: Deploy hosts and image names are long, but a checklist that spans a wide
#: terminal is hard to read, so the panel stops growing here.
MAX_PANEL_WIDTH = 100

#: Room for a detail line once the panel's borders, padding and icon are
#: taken out, so a long image name shortens instead of reflowing the panel.
_PANEL_CHROME_WIDTH = 12

_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")


def _new_log_path():
    """A file to keep the full output of one run."""
    handle, path = tempfile.mkstemp(prefix="dallinger-deploy-", suffix=".log")
    os.close(handle)
    return path


def _terminal_fd():
    """Standard output's descriptor, if it really is a terminal."""
    try:
        fd = sys.__stdout__.fileno()
    except (AttributeError, ValueError, io.UnsupportedOperation, OSError):
        return None
    return fd if os.isatty(fd) else None


class _FdCapture:
    """Redirects file descriptors 1 and 2 into ``sink``.

    Replacing ``sys.stdout`` only catches code that writes through Python.
    Child processes inherit the descriptors themselves, so a build tool or
    an ``ssh`` invocation would still draw over the panel. Holding the
    descriptors for the duration is what makes the panel the only thing on
    the terminal, whoever is writing.
    """

    def __init__(self, sink):
        self._sink = sink
        read_fd, write_fd = os.pipe()
        self._saved = {fd: os.dup(fd) for fd in (1, 2)}
        # A private handle on the real terminal, for the panel itself.
        self.terminal = os.fdopen(os.dup(1), "w", buffering=1, errors="replace")
        for fd in (1, 2):
            os.dup2(write_fd, fd)
        os.close(write_fd)
        self._reader = threading.Thread(target=self._pump, args=(read_fd,), daemon=True)
        self._reader.start()

    def _pump(self, read_fd):
        with os.fdopen(read_fd, "rb", buffering=0) as pipe:
            while True:
                chunk = pipe.read(4096)
                if not chunk:
                    return
                self._sink.write(chunk.decode("utf-8", errors="replace"))

    def close(self):
        """Give the descriptors back and stop reading."""
        for fd, saved in self._saved.items():
            os.dup2(saved, fd)
            os.close(saved)
        self._saved = {}
        # The pipe's last writer is gone, so the reader sees end of file.
        self._reader.join(timeout=5)
        self.terminal.flush()
        self.terminal.close()


class _Transcript:
    """Collects everything written while the checklist owns the terminal.

    Stands in for ``sys.stdout`` and ``sys.stderr`` so that chatty progress
    output lands in the panel as the running step's detail line instead of
    scrolling past it. Nothing is discarded: every line is appended to a log
    file, which is replayed if a step fails and whose path is printed at the
    end of the run.

    ``fileno`` deliberately raises, because that is how
    :func:`dallinger.utils.wrap_subprocess_call` detects that it must
    capture a child process's output rather than hand it the terminal.
    """

    def __init__(self, path, on_line):
        self._file = open(path, "w", encoding="utf-8", errors="replace")
        self._on_line = on_line
        self._pending = ""
        self.path = path

    def write(self, text):
        if not isinstance(text, str):
            text = text.decode("utf-8", errors="replace")
        self._pending += text
        # Progress output often overwrites a line with \r rather than \n.
        while True:
            split = min(
                (
                    i
                    for i in (self._pending.find("\n"), self._pending.find("\r"))
                    if i >= 0
                ),
                default=-1,
            )
            if split < 0:
                break
            line, self._pending = self._pending[:split], self._pending[split + 1 :]
            self._emit(line)
        return len(text)

    def _emit(self, line):
        clean = _ANSI.sub("", line).rstrip()
        self._file.write(clean + "\n")
        if clean.strip():
            self._on_line(clean.strip())

    def flush(self):
        if self._pending:
            self._emit(self._pending)
            self._pending = ""
        self._file.flush()

    def tell(self):
        """Where the log has reached, so a step can replay its own slice."""
        self.flush()
        return self._file.tell()

    def read_from(self, offset):
        """Everything logged since ``offset``."""
        self.flush()
        with open(self.path, encoding="utf-8", errors="replace") as handle:
            handle.seek(offset)
            return handle.read()

    def close(self):
        self.flush()
        self._file.close()

    def isatty(self):
        return False

    def fileno(self):
        raise io.UnsupportedOperation("The step checklist owns the terminal.")

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    @property
    def encoding(self):
        return "utf-8"

    def writable(self):
        return True

    def readable(self):
        return False

    def seekable(self):
        return False


_active = None


def active_steps():
    """Return the :class:`StepProgress` owning the terminal, or ``None``."""
    return _active


def _logging_handlers():
    """Every stream handler reachable from the logging hierarchy."""
    managed = [logging.getLogger()] + [
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    ]
    handlers = [
        handler
        for logger in managed
        for handler in logger.handlers
        if isinstance(handler, logging.StreamHandler)
    ]
    if logging.lastResort is not None:
        handlers.append(logging.lastResort)
    return handlers


def _capture_logging_streams(terminal_streams, target):
    """Point log handlers writing to the terminal at ``target`` instead.

    A handler holding the real terminal stream would write straight past the
    panel, so for as long as the checklist is up its records go to the
    transcript like everything else.
    """
    captured = []
    for handler in _logging_handlers():
        stream = getattr(handler, "stream", None)
        if stream is None or stream is target:
            continue
        if stream not in terminal_streams:
            # Handlers writing to a file or socket do not touch the terminal.
            continue
        try:
            handler.setStream(target)
        except Exception:  # pragma: no cover - exotic handler
            logging.getLogger(__name__).debug(
                "Could not redirect %r into the step checklist", handler
            )
            continue
        captured.append((handler, stream))
    return captured


def _restore_logging_streams(captured):
    """Give captured log handlers their original streams back."""
    for handler, stream in captured:
        try:
            handler.setStream(stream)
        except Exception:  # pragma: no cover - exotic handler
            logging.getLogger(__name__).debug(
                "Could not restore the original stream for %r", handler
            )


@dataclass
class _Step:
    key: str
    label: str
    state: str = PENDING
    detail: str = None
    spinner: Spinner = None


class StepProgress:
    """A panel of declared steps, with a spinner on the one in progress.

    Use it as a context manager, then wrap each unit of work in
    :meth:`step`. A step that raises is marked failed and the panel is
    closed so the error prints below it.
    """

    def __init__(self, title, steps, subtitle=None, console=None):
        if not steps:
            raise ValueError("A step progress display needs at least one step.")
        self._steps = [_Step(key=key, label=label) for key, label in steps]
        self._by_key = {step.key: step for step in self._steps}
        if len(self._by_key) != len(self._steps):
            raise ValueError("Step keys must be unique.")
        self._title = title
        self._subtitle = subtitle
        self._console = console or Console(highlight=False)
        self._live = None
        self._announced_details = set()
        self._epilogue = []
        self._captured_handlers = []
        self._transcript = None
        self._fd_capture = None
        self._replay_offset = None
        self._replayed = False
        self._saved_stdout = None
        self._saved_stderr = None
        self._saved_console_file = None

    def __enter__(self):
        global _active
        if _active is not None:
            raise RuntimeError("A step progress display is already active.")
        _active = self
        self._start_live()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type is not None and not self._replayed:
            # Something failed between steps, so no step could replay it.
            self._stop_live()
            self._replay(self._replay_offset)
        self.stop()
        return False

    def _start_live(self):
        """Take over the terminal and divert all other output into the panel."""
        if not self._console.is_terminal:
            return
        terminal_streams = {sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__}
        if self._transcript is None:
            self._transcript = _Transcript(_new_log_path(), self.set_detail)
        # Rich resolves ``console.file`` on every write, so pin it to the real
        # terminal; otherwise the panel would be written into the transcript
        # along with everything we are diverting.
        self._saved_console_file = self._console._file
        if self._console._file is None and _terminal_fd() is not None:
            self._fd_capture = _FdCapture(self._transcript)
            self._console.file = self._fd_capture.terminal
        else:
            self._console.file = self._console.file
        self._live = Live(
            console=self._console,
            get_renderable=self.renderable,
            refresh_per_second=12,
            vertical_overflow="visible",
            # We divert output into the transcript, so Rich must not also
            # try to print it above the panel.
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._live.start(refresh=True)
        self._saved_stdout = sys.stdout
        self._saved_stderr = sys.stderr
        sys.stdout = sys.stderr = self._transcript
        self._captured_handlers = _capture_logging_streams(
            terminal_streams, self._transcript
        )
        self._replay_offset = self._mark()

    def _stop_live(self):
        """Leave the current frame on screen and give the terminal back."""
        if self._live is None:
            return
        _restore_logging_streams(self._captured_handlers)
        self._captured_handlers = []
        self._live.stop()
        self._live = None
        sys.stdout = self._saved_stdout
        sys.stderr = self._saved_stderr
        if self._fd_capture is not None:
            self._fd_capture.close()
            self._fd_capture = None
        self._console._file = self._saved_console_file
        self._transcript.flush()

    def stop(self):
        """Close the live region and release terminal ownership."""
        global _active
        self._stop_live()
        if _active is self:
            _active = None
        if self._transcript is not None:
            # Nothing the run printed is lost, even though the panel only
            # showed one line of it at a time.
            self._epilogue.append((False, f"Full log: {self._transcript.path}"))
        self._print_epilogue()
        if self._transcript is not None:
            self._transcript.close()
            self._transcript = None

    def set_heading(self, title=None, subtitle=None):
        """Update the panel title or subtitle without replacing the checklist."""
        if title is not None:
            self._title = title
        if subtitle is not None:
            self._subtitle = subtitle
        if self._live is not None:
            self._live.refresh()

    def add_epilogue(self, message, *, bold=False):
        """Print ``message`` after the panel closes (URLs, passwords, commands)."""
        self._epilogue.append((bold, message))

    def _print_epilogue(self):
        from dallinger.utils import print_bold, print_status

        for bold, message in self._epilogue:
            if bold:
                print_bold(message)
            else:
                print_status(message)
        self._epilogue = []

    @contextmanager
    def step(self, key):
        """Run a declared step, ticking it on success and marking failure."""
        step = self._by_key[key]
        self._replay_offset = self._mark()
        self._set_state(step, RUNNING)
        try:
            yield step
        except BaseException:
            self._set_state(step, FAILED)
            # Close the panel so the error is not overwritten by a refresh.
            self._stop_live()
            self._replay(self._replay_offset, step=step)
            self.stop()
            raise
        self._set_state(step, DONE)
        self._replay_offset = self._mark()

    def _mark(self):
        """Where the log has reached, so a failure can replay from here."""
        return self._transcript.tell() if self._transcript is not None else None

    def _replay(self, offset, step=None):
        """Print everything produced since ``offset``, in full.

        The panel only had room for one line at a time, so on failure we
        show the whole thing rather than make the operator go find the log.
        """
        self._replayed = True
        if offset is None or self._transcript is None:
            return
        captured = self._transcript.read_from(offset).strip()
        if not captured:
            return
        from dallinger.utils import print_status

        if step is None:
            print_status("Output before the error:")
        else:
            print_status(f"Output from the failed step ({step.label}):")
        print_status(captured)

    def skip(self, key, detail=None):
        """Mark a declared step as not needed for this run."""
        step = self._by_key[key]
        step.detail = detail
        self._set_state(step, SKIPPED)

    def set_detail(self, detail):
        """Annotate the running step, for example with its latest output line."""
        step = self._running_step()
        if step is None:
            return
        step.detail = self._fit_detail(step, detail)
        if self._live is not None:
            # The live region refreshes on its own; forcing a refresh per
            # captured line would make a chatty step redraw hundreds of times.
            return
        if detail is not None and detail not in self._announced_details:
            self._announced_details.add(detail)
            self._console.print(detail)

    def _fit_detail(self, step, detail):
        """Shorten ``detail`` so the panel keeps its shape."""
        if not detail:
            return detail
        available = (
            min(self._console.width, MAX_PANEL_WIDTH)
            - _PANEL_CHROME_WIDTH
            - len(step.label)
        )
        if available < 12:
            return None
        if len(detail) <= available:
            return detail
        return detail[: available - 1] + "…"

    def _running_step(self):
        for step in self._steps:
            if step.state == RUNNING:
                return step
        return None

    def _set_state(self, step, state):
        step.state = state
        step.spinner = Spinner("dots", style="cyan") if state == RUNNING else None
        if state == DONE:
            # A finished step needs no wait annotation; a failed one keeps it.
            step.detail = None
        if self._live is not None:
            self._live.refresh()
        else:
            self._console.print(f"{_PLAIN_PREFIXES[state]} {self._plain_label(step)}")

    def _plain_label(self, step):
        if step.detail:
            return f"{step.label} ({step.detail})"
        return step.label

    def renderable(self):
        """The checklist panel, framed by the panel for the whole operation."""
        checklist = Table.grid(padding=(0, 1))
        checklist.add_column(width=1, no_wrap=True)
        # A fixed height keeps the live region's repaint arithmetic simple.
        checklist.add_column(no_wrap=True, overflow="ellipsis")
        for step in self._steps:
            checklist.add_row(self._icon(step), self._label(step))
        inner = Panel(checklist, box=box.SQUARE, border_style="dim", padding=(0, 1))
        return Panel(
            inner,
            title=self._title,
            subtitle=self._subtitle,
            box=box.SQUARE,
            padding=(0, 1),
            width=min(self._console.width, MAX_PANEL_WIDTH),
        )

    def _icon(self, step):
        if step.state == RUNNING:
            return step.spinner
        glyph, style = _ICONS[step.state]
        return Text(glyph, style=style)

    def _label(self, step):
        label = Text(step.label, style=_LABEL_STYLES[step.state])
        if step.detail:
            label.append(f"  {step.detail}", style="dim")
        return label


@contextmanager
def ssh_launch_progress(title, steps, subtitle=None, console=None):
    """Run ``steps`` in the current checklist, or start one if none is live.

    ``psynet debug ssh`` starts the panel before Dallinger runs. Dallinger
    then continues the same list instead of opening a second rectangle. The
    command that started the panel keeps the title, because it is the one
    that knows what the operator asked for; a nested caller may only add the
    subtitle it discovers later, such as the experiment URL.
    """
    existing = active_steps()
    if existing is not None:
        existing.set_heading(subtitle=subtitle)
        yield existing
        return
    with StepProgress(title, steps, subtitle=subtitle, console=console) as progress:
        yield progress
