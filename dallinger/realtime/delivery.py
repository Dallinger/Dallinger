"""Views reach players' pages on the ``dallinger_direct`` channel.

Runners send each player's page its views over the websocket the page opened
to join its session. Each view arrives as a frame whose payload is a JSON
object:

- ``type``: ``"realtime_view"``
- ``session_id``: the session the view is from
- ``view``: the view envelope, an object holding the view and what the page
  needs to know about it:

  - ``view``: the player's view of the state, from
    :meth:`~dallinger.realtime.RealtimeGame.view`
  - ``time``: the session time the view shows
  - ``number``: counts the times the session has sent views, so a later view
    has a higher number
  - ``kind``: ``"tick"`` if the view was sent after a tick, otherwise
    ``"message"``
  - ``last_processed``: the number of the latest message from this page that
    the game has applied or refused, or ``null``
  - ``rejected``: the messages from this page that
    :meth:`~dallinger.realtime.RealtimeGame.apply` refused since the
    page's last view, each a ``{"number", "reason"}`` object with the reason
    it gave :class:`~dallinger.realtime.Reject`
  - ``ended``: why the session ended, once it has, otherwise ``null``
  - ``clock``: the runner's clock when it sent the view, in seconds since
    1970

A message's number is the one its page put in the message's envelope, as
:mod:`dallinger.realtime.session_sockets` describes.

Once a session's ending is saved in Postgres, each player who isn't a bot gets
one more frame, on every page they have open:

- ``type``: ``"realtime_saved"``
- ``session_id``: the session that ended
- ``status``: the session's
  :attr:`~dallinger.models.RealtimeSession.status`, ``"ended"`` or
  ``"failed"``
- ``reason``: why the session ended
- ``view``: the player's final view

It can arrive before the player's last ``realtime_view``, so a page can end on
it alone. A page that joins just as its session ends may get no view at all,
but it gets this frame.

A page whose socket joins a session that has already ended gets no views. If
the ending is saved, the socket gets the ``realtime_saved`` frame. Otherwise it
gets a ``realtime_ended`` frame, and ``realtime_saved`` follows once the ending
is saved:

- ``type``: ``"realtime_ended"``
- ``session_id``: the session that ended
- ``reason``: why the session ended
- ``view``: the player's final view

The two frames can arrive in either order, so a page that has its session's
``realtime_saved`` frame can ignore a later ``realtime_ended``. A page can also
get ``realtime_saved`` twice.

A view goes to the page it's for, named by the participant id and the scope
the page's socket gave. A page that gave no scope is fine while a player has
one page open at a time, as in a single-page experiment, but its views reach
every page that player has open, whatever their scopes.
"""

import json

from dallinger.db import DIRECT_CHANNEL, direct_envelope, redis_conn


def view_batch(origin, passes):
    """Return the envelope for passes' views, with one send for each page's
    view, as :func:`~dallinger.db.direct_envelope` makes it, or ``None`` if
    they have no views.

    :param origin: names the runner, a string
    :param passes: a ``(session_id, views)`` pair for each session, where
        ``views`` are the ``views`` of a
        :class:`~dallinger.realtime.core.PassResult`
    """
    items = [
        {
            "participant_ids": [each["participant"]],
            "scope": each["scope"],
            "payload": json.dumps(
                {
                    "type": "realtime_view",
                    "session_id": session_id,
                    "view": each["view"],
                }
            ),
        }
        for session_id, views in passes
        for each in views
    ]
    if not items:
        return None
    return direct_envelope(origin, items)


def ending_payload(session_id, ending, participant):
    """Return the payload that tells a player's page how its session ended:
    a ``realtime_saved`` frame's if the ending is saved, otherwise a
    ``realtime_ended`` frame's.

    :param ending: the session's ending, as
        :func:`~dallinger.realtime.store.load_ending` returns it
    :param participant: the player's participant id, a string
    """
    payload = {
        "type": "realtime_ended",
        "session_id": session_id,
        "reason": ending["reason"],
        "view": ending["views"].get(participant),
    }
    if ending["status"] is not None:
        payload.update(type="realtime_saved", status=ending["status"])
    return json.dumps(payload)


def publish_saved(origin, session_id, ending):
    """Tell each player's pages that the session's ending is saved, with the
    session's status, the ending's reason and the player's final view.

    :param origin: names the sender, a string
    :param ending: the session's saved ending, as
        :func:`~dallinger.realtime.store.load_ending` returns it
    """
    items = [
        {
            "participant_ids": [player],
            "scope": None,
            "payload": ending_payload(session_id, ending, player),
        }
        for player in ending["views"]
    ]
    redis_conn.publish(DIRECT_CHANNEL, direct_envelope(origin, items))


def publish_views(origin, passes):
    """Publish passes' views to the web processes in one batch envelope, if
    they have any, taking the same arguments as :func:`view_batch`.
    """
    batch = view_batch(origin, passes)
    if batch is not None:
        redis_conn.publish(DIRECT_CHANNEL, batch)
