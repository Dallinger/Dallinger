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
- **One owner of the live region.** A terminal has one cursor, so at most
  one :class:`StepProgress` may be live per process. While one is live,
  :func:`active_steps` returns it, and anything else that would animate
  (the launch wait bar, ``yaspin`` spinners) must report through it with
  :meth:`StepProgress.set_detail` instead of drawing on its own.
- **Steps are declared up front.** The operator should see what is still
  coming. A step that turns out to be unnecessary is marked skipped rather
  than removed, so the list never reflows while it is on screen.
- **No information is hidden.** Rich redirects ``stdout`` while the panel is
  live, so output written inside a step (remote command failures, warnings)
  appears above the panel. Facts worth copying, such as URLs and passwords,
  are printed by the caller after the panel closes; this module does not
  store them.
- **Non-interactive output stays a log.** Without a terminal there is no
  live region at all: each step start and outcome prints one plain line, so
  CI logs and redirected output keep the same information in order.
"""

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

_active = None


def active_steps():
    """Return the :class:`StepProgress` owning the terminal, or ``None``."""
    return _active


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

    def __enter__(self):
        global _active
        if _active is not None:
            raise RuntimeError("A step progress display is already active.")
        _active = self
        if self._console.is_terminal:
            self._live = Live(
                console=self._console,
                get_renderable=self.renderable,
                refresh_per_second=12,
            )
            self._live.start(refresh=True)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.stop()
        return False

    def stop(self):
        """Close the live region and release terminal ownership."""
        global _active
        if self._live is not None:
            self._live.stop()
            self._live = None
        if _active is self:
            _active = None

    @contextmanager
    def step(self, key):
        """Run a declared step, ticking it on success and marking failure."""
        step = self._by_key[key]
        self._set_state(step, RUNNING)
        try:
            yield step
        except BaseException:
            self._set_state(step, FAILED)
            # Close the panel so the error is not overwritten by a refresh.
            self.stop()
            raise
        self._set_state(step, DONE)

    def skip(self, key, detail=None):
        """Mark a declared step as not needed for this run."""
        step = self._by_key[key]
        step.detail = detail
        self._set_state(step, SKIPPED)

    def set_detail(self, detail):
        """Annotate the running step, for example with a wait message."""
        step = self._running_step()
        if step is None:
            return
        step.detail = detail
        if self._live is not None:
            self._live.refresh()
        elif detail is not None and detail not in self._announced_details:
            self._announced_details.add(detail)
            self._console.print(detail)

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
        checklist.add_column(overflow="fold")
        for step in self._steps:
            checklist.add_row(self._icon(step), self._label(step))
        inner = Panel(checklist, box=box.SQUARE, border_style="dim", padding=(0, 1))
        return Panel(
            inner,
            title=self._title,
            subtitle=self._subtitle,
            box=box.SQUARE,
            padding=(0, 1),
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
