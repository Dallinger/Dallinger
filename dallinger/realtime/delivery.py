"""How views reach players' pages.

Runners send each player's page its views over the websocket the page opened
to join its session, on the ``dallinger_direct`` channel. Each view arrives as
a frame whose payload is a JSON object:

- ``type``: ``"realtime_view"``
- ``session_id``: the session the view is from
- ``view``: the view envelope, an object holding the view and what the page
  needs to know about it:

  - ``view``: the player's view of the state, from
    :meth:`~dallinger.realtime.game.RealtimeGame.view`
  - ``time``: the session time the view shows
  - ``number``: counts the times the session has sent views, so a later view
    has a higher number
  - ``kind``: ``"tick"`` if the view was sent after a tick, otherwise
    ``"message"``
  - ``last_processed``: the number of the latest message from this page that
    the game has applied or refused, or ``null``
  - ``rejected``: the messages from this page that
    :meth:`~dallinger.realtime.game.RealtimeGame.apply` refused since the
    page's last view, each a ``{"number", "reason"}`` object with the reason
    it gave :class:`~dallinger.realtime.game.Reject`
  - ``ended``: why the session ended, once it has, otherwise ``null``
  - ``clock``: the runner's clock when it sent the view, in seconds since
    1970

A message's number is the one the client helpers put in its envelope, as
:class:`~dallinger.realtime.game.Sent` describes.

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
it alone.

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


def publish_saved(origin, session_id, status, ending):
    """Tell each player's pages that the session's ending is saved, with the
    session's ``status``, the ending's reason and the player's final view.

    :param origin: names the sender, a string
    :param ending: the ``reason`` and final ``views`` of the session, as
        :func:`~dallinger.realtime.store.load_ending` returns them
    """
    items = [
        {
            "participant_ids": [player],
            "scope": None,
            "payload": json.dumps(
                {
                    "type": "realtime_saved",
                    "session_id": session_id,
                    "status": status,
                    "reason": ending["reason"],
                    "view": view,
                }
            ),
        }
        for player, view in ending["views"].items()
    ]
    redis_conn.publish(DIRECT_CHANNEL, direct_envelope(origin, items))


def publish_views(origin, passes):
    """Publish passes' views to the web processes in one batch envelope, if
    they have any, taking the same arguments as :func:`view_batch`.
    """
    batch = view_batch(origin, passes)
    if batch is not None:
        redis_conn.publish(DIRECT_CHANNEL, batch)
