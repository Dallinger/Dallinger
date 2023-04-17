import random
from datetime import datetime

import gevent
import pytest


class DummyEvent(object):
    creation_time = None
    type = "event"
    id = 1

    def __init__(self, creation_time):
        self.creation_time = creation_time


class DummyEvents(list):
    def count(self):
        return len(self)


class DummyExperiment(object):
    replay_path = "/replay"
    _events = DummyEvents()
    replayed = []
    finished = False
    started = False

    def log(self, *args, **kw):
        pass

    def replay_started(self):
        return self.started

    def events_for_replay(self, *args, **kwargs):
        return self._events

    def replay_event(self, event):
        self.replayed.append(
            {"orig_time": event.creation_time, "replay_time": datetime.now()}
        )

    def replay_finish(self):
        self.finished = True


@pytest.mark.slow
class TestReplayBackend:
    allowed_jitter = 0.05

    def launch_replay_task(self, exp):
        from dallinger.experiment_server.replay import ReplayBackend

        task = ReplayBackend(exp)
        gevent.spawn(task)
        return task

    def wait_to_finish(self, exp):
        loop_count = 0
        while exp.finished is False:
            gevent.sleep(2)
            loop_count += 1
            if loop_count > 10:
                raise RuntimeError("Replay did not finish in reasonable time")

    def test_replay_waits_to_start(self):
        exp = DummyExperiment()
        assert exp.started is False
        assert exp.finished is False

        self.launch_replay_task(exp)

        # Wait for task to `run` in background
        gevent.sleep(2)
        assert exp.finished is False

        # Start the task
        exp.started = True
        gevent.sleep(2)
        assert exp.finished is True

    def test_replay_event_timing(self):
        exp = DummyExperiment()

        # 10 events ~ 1 second apart with some random jitter
        exp._events = DummyEvents(
            [
                DummyEvent(datetime(2010, 1, 1, 0, 0, t, int(random.random() * 1000)))
                for t in range(10)
            ]
        )

        exp.started = True
        self.launch_replay_task(exp)

        self.wait_to_finish(exp)

        replayed = exp.replayed
        assert len(replayed) == 10

        base_offset = (
            replayed[0]["replay_time"] - replayed[0]["orig_time"]
        ).total_seconds()

        for rp in replayed:
            time_diff = (rp["replay_time"] - rp["orig_time"]).total_seconds()
            assert abs(time_diff - base_offset) <= self.allowed_jitter
