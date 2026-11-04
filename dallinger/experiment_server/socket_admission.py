"""Deciding whether a websocket connection may open.

An ``/experiment-socket`` connection must name a participant that exists and
carry that participant's token in the ``participant_token`` query parameter,
the experiment must build, and the experiment's
:func:`~dallinger.experiment.Experiment.accept_websocket_connection` must
accept it. :func:`admit` checks all of these before the connection subscribes
to anything, and raises :class:`Refused` otherwise. A ``/chat`` connection
that names a participant is checked by :func:`authenticate` alone.
"""

import logging

from gevent.lock import Semaphore
from sqlalchemy.exc import SQLAlchemyError

from dallinger import models
from dallinger.db import session
from dallinger.utils import normalized_participant_id

from .experiment_server import Experiment

logger = logging.getLogger(__name__)


class Refused(Exception):
    """A connection that may not open, and the reason to close it with.

    ``retry`` is true when the failure is the server's, so the browser should
    try again, and false when the connection itself is refused.
    """

    def __init__(self, reason, retry=False):
        super().__init__(reason)
        self.reason = reason
        self.retry = retry


_process_experiment = None
_process_experiment_lock = Semaphore()


def process_experiment():
    """The one ``Experiment`` this process hands to its experiment-socket clients.

    ``Experiment.__init__`` runs ``configure()``, which is experiment code and
    may query, so the constructor can yield and two connections would otherwise
    each build one.
    """
    global _process_experiment
    with _process_experiment_lock:
        if _process_experiment is None:
            try:
                _process_experiment = Experiment()
            finally:
                session.remove()
    return _process_experiment


def resolve_participant_id(participant_id, token):
    """The id of the participant ``participant_id`` names, or ``None``.

    ``None`` is also returned when ``token`` isn't that participant's token.
    The participant is looked up by the normalized id, so a value the column
    cannot hold is refused before a query is made with it.
    """
    normalized = normalized_participant_id(participant_id)
    if normalized is None:
        return None
    try:
        token_hash = (
            session.query(models.Participant.auth_token_hash)
            .filter_by(id=int(normalized))
            .scalar()
        )
    finally:
        session.remove()
    return normalized if models.auth_token_matches(token_hash, token) else None


def authenticate(requested_id, token):
    """The participant id of a connection that names ``requested_id``.

    :raises Refused: unless the participant exists and ``token`` is theirs,
        and with ``retry`` set when the lookup fails
    """
    try:
        participant_id = resolve_participant_id(requested_id, token)
    except SQLAlchemyError:
        logger.exception(
            "Could not look up participant %r for a websocket.", requested_id
        )
        raise Refused("participant lookup failed", retry=True)
    if participant_id is None:
        logger.warning(
            "Refusing websocket for participant %r: unknown participant or "
            "wrong token.",
            requested_id,
        )
        raise Refused("unknown participant or wrong token")
    return participant_id


def admit(requested_id, scope, token):
    """The participant id and the experiment for a new connection.

    Every message is handed to the experiment as coming from a participant, so
    a connection that names none is refused, as is one without that
    participant's ``token``. The experiment's hook is where an experiment can
    check more. The session is removed after each step, because an accepted
    connection can then idle in ``receive()`` indefinitely.

    :raises Refused: for an unknown participant, a wrong token or a
        connection the experiment refuses, and with ``retry`` set when a
        lookup, the experiment or its hook fails
    """
    participant_id = authenticate(requested_id, token)
    try:
        experiment = process_experiment()
    except Exception:
        logger.exception("Could not build the experiment.")
        raise Refused("experiment unavailable", retry=True)
    try:
        accepted = experiment.accept_websocket_connection(participant_id, scope)
    except Exception:
        logger.exception(
            "Error in accept_websocket_connection for participant %s.", participant_id
        )
        raise Refused("connection check failed", retry=True)
    finally:
        session.remove()
    if not accepted:
        logger.warning("The experiment refused participant %s.", participant_id)
        raise Refused("refused by the experiment")
    return participant_id, experiment
