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

A view goes to the page it's for, named by the participant id and the scope
the page's socket gave. A page that gave no scope is fine while a player has
one page open at a time, as in a single-page experiment, but its views reach
every page that player has open, whatever their scopes.
"""

import json

from dallinger.db import DIRECT_CHANNEL, redis_conn


def view_batch(origin, passes):
    """Return the batch envelope for passes' views, as JSON text, or ``None``
    if they have no views.

    A batch envelope is a JSON dict holding the ``origin`` of the message and
    its ``items``, a list of directed sends. Each send holds a list of
    ``participant_ids``, a ``scope`` (a string, or ``None`` for every page),
    and the ``payload`` to send them, as JSON text.

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
    return json.dumps({"origin": origin, "items": items})


def publish_views(origin, passes):
    """Publish passes' views to the web processes in one batch envelope, if
    they have any, taking the same arguments as :func:`view_batch`.
    """
    batch = view_batch(origin, passes)
    if batch is not None:
        redis_conn.publish(DIRECT_CHANNEL, batch)
