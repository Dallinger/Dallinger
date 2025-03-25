import logging
import time

import gevent

from dallinger.utils import get_base_url

logger = logging.getLogger(__name__)


class ReplayBackend(object):
    """Replay backend which replays `events` from a completed experiment run.

    This is started during launch and delegates `event` selection and
    publication to the experiment class. `Events` are any objects with a
    creation_time attribute.
    """

    def __init__(self, experiment):
        self.experiment = experiment

    def __call__(self):
        gevent.sleep(0.200)

        try:
            logger.info(
                "Replay ready: {}{}".format(get_base_url(), self.experiment.replay_path)
            )
        except RuntimeError:
            # config not loaded, we may be in unit tests
            pass

        while not self.experiment.replay_started():
            gevent.sleep(0.01)

        self.experiment.log("Looping through replayable data", key="replay")
        timestamp = self.timestamp
        events = self.experiment.events_for_replay()

        if not events.count():
            self.experiment.replay_finish()
            return

        first_timestamp = timestamp(events[0].creation_time)
        self.experiment.log(
            "Found {} messages to replay starting from {}".format(
                events.count(), events[0].creation_time
            ),
            key="replay",
        )
        start = time.time()
        for event in events:
            event_offset = timestamp(event.creation_time) - first_timestamp
            cur_offset = time.time() - start
            if event_offset >= cur_offset:
                if (event_offset - cur_offset) > 1:
                    self.experiment.log(
                        "Waiting {} seconds to replay {} {}".format(
                            event_offset - cur_offset, event.type, event.id
                        ),
                        key="replay",
                    )
                gevent.sleep(event_offset - cur_offset)
            self.experiment.replay_event(event)

        self.experiment.log(
            "Replayed {} events in {} seconds (original duration {} seconds)".format(
                events.count(),
                time.time() - start,
                timestamp(event.creation_time) - first_timestamp,
            ),
            key="replay",
        )
        self.experiment.replay_finish()
        return

    @staticmethod
    def timestamp(dt):
        """Generate a microsecond accurate timestamp from a datetime."""
        return time.mktime(dt.timetuple()) + dt.microsecond / 1e6
