import json
from unittest.mock import Mock

from dallinger.db import REALTIME_SESSION_CHANNEL
from dallinger.realtime import delivery


def page_view(participant, scope, number):
    return {"participant": participant, "scope": scope, "view": {"number": number}}


def test_a_batch_has_one_send_per_page_view():
    batch = delivery.view_batch(
        "a runner",
        [
            (4, [page_view("1", "page", 7), page_view("2", None, 7)]),
            (5, []),
            (6, [page_view("1", "page", 2)]),
        ],
    )

    assert json.loads(batch) == {
        "origin": "a runner",
        "items": [
            {
                "participant_ids": ["1"],
                "scope": "page",
                "payload": json.dumps(
                    {"type": "realtime_view", "session_id": 4, "view": {"number": 7}}
                ),
            },
            {
                "participant_ids": ["2"],
                "scope": None,
                "payload": json.dumps(
                    {"type": "realtime_view", "session_id": 4, "view": {"number": 7}}
                ),
            },
            {
                "participant_ids": ["1"],
                "scope": "page",
                "payload": json.dumps(
                    {"type": "realtime_view", "session_id": 6, "view": {"number": 2}}
                ),
            },
        ],
    }


def test_views_go_out_in_one_message_and_none_go_out_without_views(monkeypatch):
    redis_conn = Mock()
    monkeypatch.setattr(delivery, "redis_conn", redis_conn)
    passes = [(4, [page_view("1", "page", 7)]), (5, [page_view("3", "tab", 2)])]

    delivery.publish_views("a runner", [(4, []), (5, [])])
    delivery.publish_views("a runner", passes)

    redis_conn.publish.assert_called_once_with(
        REALTIME_SESSION_CHANNEL, delivery.view_batch("a runner", passes)
    )
