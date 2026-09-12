import io
import logging
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from rich.console import Console

from dallinger.step_progress import (
    DONE,
    FAILED,
    PENDING,
    RUNNING,
    SKIPPED,
    StepProgress,
    active_steps,
    latest_log_path,
)

STEPS = [("first", "Check the server"), ("second", "Launch the experiment")]


def plain_console():
    """A console without a terminal, so the checklist logs plain lines."""
    return Console(file=io.StringIO(), force_terminal=False, width=70)


def terminal_console():
    return Console(file=io.StringIO(), force_terminal=True, width=70)


def test_checklist_is_nested_in_a_panel_for_the_whole_operation():
    console = terminal_console()
    steps = StepProgress("Deploying dlgr-1", STEPS, console=console)

    console.print(steps.renderable())
    lines = console.file.getvalue().splitlines()

    assert "Deploying dlgr-1" in lines[0]
    # Outer frame, then the checklist's own frame inside it.
    assert lines[0].startswith("┌") and lines[1].lstrip("│ ").startswith("┌")
    assert all(step.state == PENDING for step in steps._steps)


def test_steps_are_ticked_as_they_succeed():
    console = plain_console()
    steps = StepProgress("Deploying", STEPS, console=console)

    with steps:
        assert active_steps() is steps
        for key in ("first", "second"):
            with steps.step(key):
                assert steps._by_key[key].state == RUNNING

    assert [step.state for step in steps._steps] == [DONE, DONE]
    assert console.file.getvalue().splitlines() == [
        "→ Check the server",
        "✓ Check the server",
        "→ Launch the experiment",
        "✓ Launch the experiment",
    ]
    assert active_steps() is None


def test_failed_step_is_marked_and_releases_the_terminal():
    steps = StepProgress("Deploying", STEPS, console=plain_console())

    with pytest.raises(ValueError):
        with steps:
            with steps.step("first"):
                raise ValueError("remote command failed")

    assert [step.state for step in steps._steps] == [FAILED, PENDING]
    assert active_steps() is None


def test_skipped_step_keeps_its_place_with_a_reason():
    steps = StepProgress("Updating", STEPS, console=plain_console())

    with steps:
        with steps.step("first"):
            pass
        steps.skip("second", detail="update mode")

    second = steps._by_key["second"]
    assert (second.state, second.detail) == (SKIPPED, "update mode")


def test_detail_annotates_the_running_step_once_per_message():
    console = plain_console()
    steps = StepProgress("Deploying", STEPS, console=console)

    with steps:
        with steps.step("first"):
            steps.set_detail("waiting for HTTPS (attempt 1 of 2)")
            steps.set_detail("waiting for HTTPS (attempt 1 of 2)")
            assert steps._by_key["first"].detail is not None

    # Without a terminal the annotation is logged, and not repeated.
    logged = console.file.getvalue().splitlines()
    assert logged.count("waiting for HTTPS (attempt 1 of 2)") == 1
    # A finished step carries no wait annotation.
    assert steps._by_key["first"].detail is None


def test_only_one_display_may_own_the_terminal():
    outer = StepProgress("Deploying", STEPS, console=plain_console())
    inner = StepProgress("Deploying", STEPS, console=plain_console())

    with outer:
        with pytest.raises(RuntimeError):
            inner.__enter__()

    assert active_steps() is None


def test_ssh_launch_progress_reuses_the_live_checklist():
    console = plain_console()
    from dallinger.step_progress import ssh_launch_progress

    outer = StepProgress("Debugging app", STEPS, console=console)
    with outer:
        with ssh_launch_progress("Deploying app", STEPS, subtitle="host") as inner:
            assert inner is outer
            # The command that started the panel keeps the title.
            assert outer._title == "Debugging app"
            assert outer._subtitle == "host"
            with inner.step("first"):
                pass
    assert active_steps() is None


def test_panel_spans_the_whole_terminal_width():
    console = Console(file=io.StringIO(), force_terminal=True, width=200, height=40)
    steps = StepProgress("Deploying dlgr-1", STEPS, console=console)

    console.print(steps.renderable())
    widths = {len(line.rstrip()) for line in console.file.getvalue().splitlines()}

    assert widths == {200}


def test_output_becomes_the_running_step_detail_and_is_logged():
    console = terminal_console()
    steps = StepProgress("Deploying", STEPS, console=console)

    with steps:
        with steps.step("first") as step:
            print("=> [2/8] RUN pip install")
            assert step.detail == "=> [2/8] RUN pip install"
            # Nothing reached the terminal.
            assert "pip install" not in console.file.getvalue()
        log_path = steps._transcript.path

    assert "=> [2/8] RUN pip install" in Path(log_path).read_text()


def test_latest_log_symlink_can_be_followed_during_the_run(tmp_path, monkeypatch):
    real_mkstemp = tempfile.mkstemp

    monkeypatch.setattr(
        "dallinger.step_progress.tempfile.gettempdir", lambda: str(tmp_path)
    )
    monkeypatch.setattr(
        "dallinger.step_progress.tempfile.mkstemp",
        lambda prefix, suffix: real_mkstemp(
            prefix=prefix, suffix=suffix, dir=str(tmp_path)
        ),
    )

    console = terminal_console()
    steps = StepProgress("Deploying", STEPS, console=console)
    with steps:
        with steps.step("first"):
            print("building")
            latest = Path(latest_log_path())
            assert latest.is_symlink()
            assert latest.resolve() == Path(steps._transcript.path).resolve()
            # Flushed as it arrives, so tail -f can read it mid-run.
            assert "building" in latest.read_text()


def test_log_records_are_diverted_into_the_panel():
    console = terminal_console()
    handler = logging.StreamHandler(sys.__stdout__)
    logger = logging.getLogger("dallinger.tests.step_progress")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        steps = StepProgress("Deploying", STEPS, console=console)
        with steps:
            with steps.step("first") as step:
                logger.warning("Ignoring constraints.txt in in-repo experiment")
                assert step.detail == "Ignoring constraints.txt in in-repo experiment"
        assert handler.stream is sys.__stdout__
    finally:
        logger.removeHandler(handler)


def test_a_failed_step_replays_its_output_in_full(capsys):
    console = terminal_console()
    steps = StepProgress("Deploying", STEPS, console=console)

    with pytest.raises(RuntimeError):
        with steps:
            with steps.step("first"):
                print("#5 [3/8] RUN pip install")
                print("ERROR: failed to solve")
                raise RuntimeError("build failed")

    printed = capsys.readouterr().out
    assert "Output from the failed step (Check the server)" in printed
    assert "#5 [3/8] RUN pip install" in printed
    assert "ERROR: failed to solve" in printed
    assert "Full log: " in printed
    assert "Follow: tail -f " in printed


def test_an_error_between_steps_replays_output_since_the_last_step(capsys):
    console = terminal_console()
    steps = StepProgress("Deploying", STEPS, console=console)

    with pytest.raises(RuntimeError):
        with steps:
            with steps.step("first"):
                print("that step went fine")
            print("about to look up the server")
            raise RuntimeError("failed between steps")

    printed = capsys.readouterr().out
    assert "Output before the error:" in printed
    assert "about to look up the server" in printed
    # The step that succeeded has already been accounted for.
    assert "that step went fine" not in printed


def test_child_process_output_is_captured_from_the_descriptors(tmp_path):
    """A child writing to inherited descriptors must not reach the terminal."""
    from dallinger.step_progress import _FdCapture, _Transcript

    log = tmp_path / "deploy.log"
    seen = []
    transcript = _Transcript(str(log), seen.append)
    capture = _FdCapture(transcript)
    try:
        subprocess.run(["sh", "-c", "echo out; echo err >&2"], check=True)
    finally:
        capture.close()
    transcript.close()

    assert seen == ["out", "err"]
    assert log.read_text().splitlines() == ["out", "err"]


def test_a_long_detail_is_shortened_to_keep_the_panel_shape():
    console = terminal_console()
    steps = StepProgress("Deploying", STEPS, console=console)

    with steps:
        with steps.step("first") as step:
            steps.set_detail("x" * 500)
            assert len(step.detail) < console.width
            assert step.detail.endswith("…")


def test_epilogue_prints_after_the_panel_closes(capsys):
    console = plain_console()
    steps = StepProgress("Deploying", STEPS, console=console)
    with steps:
        with steps.step("first"):
            pass
        steps.add_epilogue("Dashboard: https://example.org")
        steps.add_epilogue("Follow logs: ssh example", bold=True)
        with steps.step("second"):
            pass

    assert "Dashboard: https://example.org" not in console.file.getvalue()
    captured = capsys.readouterr().out
    assert "Dashboard: https://example.org" in captured
    assert "Follow logs: ssh example" in captured


def test_unique_step_keys_are_required():
    with pytest.raises(ValueError):
        StepProgress("Deploying", [("same", "One"), ("same", "Two")])
