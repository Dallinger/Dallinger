import io

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


def test_unique_step_keys_are_required():
    with pytest.raises(ValueError):
        StepProgress("Deploying", [("same", "One"), ("same", "Two")])
