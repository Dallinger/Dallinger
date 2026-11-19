import os
import time

import gevent
import pytest
from werkzeug import _reloader

from dallinger import dev_reloader


@pytest.fixture
def stat_loop(monkeypatch):
    """Werkzeug's stat reloader, with its scan in a thread, restored after."""
    monkeypatch.setattr(
        _reloader.StatReloaderLoop, "run_step", _reloader.StatReloaderLoop.run_step
    )
    dev_reloader.scan_in_a_thread()
    loop = _reloader.StatReloaderLoop()
    loop.mtimes = {}
    loop.extra_files = set()
    loop.exclude_patterns = set()
    return loop


def test_the_reloader_still_reloads_when_a_watched_file_changes(
    stat_loop, monkeypatch, tmp_path
):
    watched = tmp_path / "experiment.py"
    watched.write_text("x = 1\n")
    monkeypatch.setattr(_reloader, "_find_stat_paths", lambda *args: [str(watched)])
    reloads = []
    monkeypatch.setattr(stat_loop, "trigger_reload", reloads.append)

    stat_loop.run_step()
    assert reloads == []
    later = time.time() + 10
    watched.write_text("x = 2\n")
    os.utime(watched, (later, later))
    stat_loop.run_step()

    assert reloads == [str(watched)]


def test_a_slow_scan_doesnt_stop_other_greenlets(stat_loop, monkeypatch):
    def slow_paths(*args):
        # A real sleep, as a scan of many files blocks its thread.
        time.sleep(0.5)
        return []

    monkeypatch.setattr(_reloader, "_find_stat_paths", slow_paths)
    ticks = []

    def ticker():
        for _ in range(10):
            ticks.append(time.monotonic())
            gevent.sleep(0.05)

    ticking = gevent.spawn(ticker)
    gevent.sleep(0.1)
    stat_loop.run_step()
    ticking.join()

    gaps = [later - earlier for earlier, later in zip(ticks, ticks[1:])]
    assert max(gaps) < 0.25
