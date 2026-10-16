"""The jobs runners queue for Dallinger's worker processes."""

import logging
import traceback
from datetime import datetime

from sqlalchemy import event

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession
from dallinger.realtime import store
from dallinger.realtime.game import FAILED

logger = logging.getLogger(__name__)


def write_records(session_id):
    """Write the session's new records to Postgres, and handle their effects.

    A runner queues this job every few seconds while a session has new
    records, and once more when the session ends. In one transaction, the job
    adds a :class:`~dallinger.models.RealtimeEvent` for each record, passes
    each effect to the game type's
    :meth:`~dallinger.realtime.game.RealtimeGame.handle_effect`, and keeps the
    latest checkpoint on the session's
    :class:`~dallinger.models.RealtimeSession`. Jobs for one session take
    turns, so each record is written once.

    If anything raises before the commit, nothing from the job is saved, and
    the session fails: its row is marked failed with the error, a session
    still running ends with the reason
    :data:`~dallinger.realtime.game.FAILED`, and the error is raised again.
    Later jobs for a failed session write nothing, and end it if it's still
    running.

    After the commit, the job removes the records it wrote from redis. An
    error there is raised without failing the session, since the next job
    starts after the last record written.
    """
    try:
        written = _write(session_id)
    except Exception as error:
        db.session.rollback()
        _fail(session_id, error)
        raise
    finally:
        db.session.remove()
    if written is not None:
        store.trim_records(session_id, written)


def _write(session_id):
    # FOR UPDATE locks the row until the transaction ends, so another job for
    # the session waits here and then reads from where this one finished. In a
    # gevent worker the wait yields to other jobs only because
    # rq_gevent_worker makes psycopg2 cooperative.
    row = (
        db.session.query(RealtimeSession)
        .filter_by(id=session_id)
        .with_for_update()
        .one()
    )
    # A job waiting for the lock keeps the runner from queuing more.
    store.start_writing_records(session_id)
    if row.status == "failed":
        db.session.commit()
        store.end_realtime_session(session_id, FAILED)
        store.delete_records(session_id)
        return None
    records = store.read_records(session_id, row.last_written_record)
    if not records:
        db.session.commit()
        return None
    game = None
    for _, record in records:
        if record["sequence"] is None:
            raise RuntimeError(
                "The session's saved state in redis can't be read, so its end "
                "record can't be written:\n{}".format(record["error"])
            )
        db.session.add(_event(session_id, record))
        if record["type"] == "checkpoint":
            row.checkpoint = record["state"]
        elif record["type"] == "effect":
            game = game or store.experiment_games()[row.game_type]
            _handle_effect(game, record["name"], record["payload"], row)
    # Saved before the commit, which expires the row.
    last_written = row.last_written_record = records[-1][0]
    db.session.commit()
    return last_written


def _handle_effect(game, name, payload, row):
    what = "{}.handle_effect, handling the effect {!r},".format(
        type(game).__name__, name
    )

    def refuse_commit(session):
        raise RuntimeError(
            "{} committed. The job commits once every new record is saved.".format(what)
        )

    session = db.session()
    transaction = session.get_transaction()
    event.listen(session, "before_commit", refuse_commit)
    try:
        game.handle_effect(name, payload, row)
    finally:
        event.remove(session, "before_commit", refuse_commit)
    if db.session().get_transaction() is not transaction:
        raise RuntimeError(
            "{} ended the job's transaction, by rolling back or closing the "
            "session.".format(what)
        )


def _event(session_id, record):
    kind = record["type"]
    fields = {
        "session_id": session_id,
        "sequence": record["sequence"],
        "event_type": kind,
        "session_time": record["time"],
    }
    if kind == "message":
        fields.update(
            participant_id=int(record["participant"]),
            scope=record["scope"],
            payload=record["payload"],
            number=record["number"],
            browser_time=record["browser_time"],
            view_time=record["view_time"],
            # Naive local time, like Dallinger's other DateTime columns.
            receive_time=datetime.fromtimestamp(record["received"]),
            status=record["status"],
        )
        # A JSONB column stores None as JSON null, so an accepted message
        # leaves the column out to keep it SQL NULL.
        if record["status"] == "rejected":
            fields["reason"] = record["reason"]
    elif kind == "effect":
        fields.update(name=record["name"], payload=record["payload"])
    elif kind == "checkpoint":
        fields.update(state=record["state"])
    elif kind == "end":
        fields.update(
            reason=record["reason"],
            outcome=record["outcome"],
            state=record["state"],
            error=record["error"],
        )
    return RealtimeEvent(**fields)


def _fail(session_id, error):
    text = "".join(traceback.format_exception(error))
    logger.error(
        "Writing the record of session %s failed, so the session fails:\n%s",
        session_id,
        text,
    )
    # The row is marked first, so the job queued when the session ends finds
    # it failed.
    try:
        db.session.query(RealtimeSession).filter(
            RealtimeSession.id == session_id, RealtimeSession.status != "failed"
        ).update({"status": "failed", "error": text})
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Session %s couldn't be marked failed.", session_id)
    try:
        store.end_realtime_session(session_id, FAILED)
    except Exception:
        logger.exception("Session %s couldn't be ended.", session_id)
