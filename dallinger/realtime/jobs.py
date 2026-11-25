"""The jobs runners queue for Dallinger's worker processes."""

import logging
import traceback
from datetime import datetime

from sqlalchemy import event

from dallinger import db
from dallinger.models import RealtimeEvent, RealtimeSession
from dallinger.realtime import store
from dallinger.realtime.delivery import publish_saved
from dallinger.realtime.game import FAILED

logger = logging.getLogger(__name__)

# The records a game type handles when they're written.
_HANDLED = ("effect", "player_end", "end")


def write_records(session_id):
    """Write the session's new records to Postgres, and handle their effects.

    A runner queues this job every few seconds while a session has new
    records, and :func:`write_ending` runs it once the session has ended. In
    one transaction, the job adds a :class:`~dallinger.models.RealtimeEvent`
    for each record, adds each player added while the session ran to its
    ``members``, passes each effect to the game type's
    :meth:`~dallinger.realtime.RealtimeGame.handle_effect` and each player's
    ending to its
    :meth:`~dallinger.realtime.RealtimeGame.handle_player_ending`, and keeps the
    latest checkpoint on the session's
    :class:`~dallinger.models.RealtimeSession`. The job that writes the
    session's end record also saves the ending on the row, with the status
    ``"failed"`` if its reason is :data:`~dallinger.realtime.game.FAILED` and
    ``"ended"`` otherwise. Jobs for one session take turns, so each record is
    written once.

    If anything raises before the commit, nothing from the job is saved, and
    the error is raised again. A session whose ending isn't saved yet fails:
    its row is marked failed with the error, and a session still running ends
    with the reason :data:`~dallinger.realtime.game.FAILED`. Later jobs for a
    failed session write nothing, and end it if it's still running.

    After the commit, the job tells the pages of each player whose ending it
    wrote that it's saved, and removes the records it wrote from redis. An
    error there is raised without failing the session, since the next job
    starts after the last record written.
    """
    try:
        written, players_ended = _write(session_id)
    except Exception as error:
        # Unlike rollback(), which ends only a savepoint the game left open.
        db.session.close()
        _fail(session_id, error)
        raise
    finally:
        db.session.remove()
    endings = {
        participant: store.note_player_ending_saved(session_id, participant)
        for participant in players_ended
    }
    publish_saved(
        "write_records",
        session_id,
        {player: ending for player, ending in endings.items() if ending is not None},
    )
    if written is not None:
        store.trim_records(session_id, written)


def write_ending(session_id):
    """Write the rest of an ended session's record, as :func:`write_records`
    does, then tell its players' pages that the ending is saved.

    The runner queues this job when it saves the session's ending. Once the
    record is written, or has failed, the session's keys in redis expire after
    :data:`~dallinger.realtime.store.ENDED_SESSION_TTL` seconds, redis notes
    that the ending is saved, and each player who isn't a bot gets a
    ``realtime_saved`` frame with the session's status and the player's final
    view, as :mod:`dallinger.realtime.delivery` describes. An error writing
    the record is raised again after that.
    """
    try:
        write_records(session_id)
    finally:
        store.expire_session(session_id)
        _publish_saved(session_id)


def _publish_saved(session_id):
    try:
        status = (
            db.session.query(RealtimeSession.status).filter_by(id=session_id).scalar()
        )
    finally:
        db.session.remove()
    # Noted before the frame goes out, so a page that joins in between and
    # finds the ending unsaved is already listening for it.
    store.note_ending_saved(session_id, status)
    # The members include every player with a final view, since a player is a
    # member before the session starts or adds them, and a player added just
    # before the session ended, who can have a page open without one.
    done = store.players_done(session_id)
    ending = store.load_ending(session_id)
    endings = {
        player: ending
        for player, is_bot in store.session_members(session_id).items()
        if not is_bot and player not in done
    }
    # A player whose own ending failed to save, which failed the session, is
    # told now.
    endings.update(store.note_unsaved_player_endings(session_id, status))
    publish_saved("write_ending", session_id, endings)


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
        return None, []
    records = store.read_records(session_id, row.last_written_record)
    if not records:
        db.session.commit()
        return None, []
    game = None
    if any(record["type"] in _HANDLED for _, record in records):
        game = store.experiment_games().get(row.game_type)
        # The runner fails a session whose game type has gone, and its
        # failed ending is written without handlers. Anything else fails.
        last = records[-1][1]
        if game is None and (last["type"], last.get("reason")) != ("end", FAILED):
            raise LookupError(
                "No game type has session {}'s channel {!r}.".format(
                    session_id, row.game_type
                )
            )
    players_ended = []
    for record_id, record in records:
        # The end record of a session whose saved state can't be read has no
        # sequence number, so it can't be an event, but its ending is saved.
        if record["sequence"] is not None:
            db.session.add(_event(session_id, record))
        if record["type"] == "checkpoint":
            row.checkpoint = record["state"]
        elif record["type"] == "effect":
            if game is not None:
                _handle_effect(game, record["name"], record["payload"], row)
        elif record["type"] == "player_add":
            _record_player_added(row, record)
        elif record["type"] == "player_end":
            if game is not None:
                ending = {
                    "time": record["time"],
                    "reason": record["reason"],
                    "outcome": record["outcome"],
                }
                _without_commits(
                    "{}.handle_player_ending".format(type(game).__name__),
                    lambda: game.handle_player_ending(
                        row, record["participant"], ending
                    ),
                )
                players_ended.append(record["participant"])
        elif record["type"] == "end":
            _record_ending(row, record_id, record)
            if game is not None:
                _without_commits(
                    "{}.handle_ending".format(type(game).__name__),
                    lambda: game.handle_ending(row),
                )
    # Saved before the commit, which expires the row.
    last_written = row.last_written_record = records[-1][0]
    db.session.commit()
    return last_written, players_ended


def _record_player_added(row, record):
    # New lists, which is what marks the columns as changed.
    participant_id = int(record["participant"])
    row.members = [*row.members, participant_id]
    if record["bot"]:
        row.bots = [*row.bots, participant_id]


def _record_ending(row, record_id, record):
    # Naive local time, like Dallinger's other DateTime columns.
    row.end_time = datetime.fromtimestamp(store.stream_id_time(record_id))
    row.end_reason = record["reason"]
    row.outcome = record["outcome"]
    row.final_state = record["state"]
    if record["reason"] == FAILED:
        row.status = "failed"
        row.error = record["error"]
    else:
        row.status = "ended"


def _handle_effect(game, name, payload, row):
    what = "{}.handle_effect, handling the effect {!r},".format(
        type(game).__name__, name
    )
    _without_commits(what, lambda: game.handle_effect(name, payload, row))


def _without_commits(what, call):
    """Run a game's ``call``, failing if it ends the job's transaction.

    The game can use savepoints (``db.session.begin_nested()``), but must
    close each one it opens.
    """

    def refuse_commit(session):
        # Releasing a savepoint the game opened also fires before_commit.
        if session.get_nested_transaction() is savepoint:
            raise RuntimeError(
                "{} committed. The job commits once every new record is saved.".format(
                    what
                )
            )

    session = db.session()
    transaction = session.get_transaction()
    savepoint = session.get_nested_transaction()
    event.listen(session, "before_commit", refuse_commit)
    try:
        call()
    finally:
        event.remove(session, "before_commit", refuse_commit)
    session = db.session()
    if session.get_transaction() is not transaction:
        raise RuntimeError(
            "{} ended the job's transaction, by rolling back or closing the "
            "session.".format(what)
        )
    # The job's commit would release only a savepoint left open.
    if session.get_nested_transaction() is not savepoint:
        raise RuntimeError("{} left a savepoint open.".format(what))


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
    elif kind == "clock":
        fields.update(
            participant_id=int(record["participant"]),
            scope=record["scope"],
            browser_time=record["browser_time"],
            receive_time=datetime.fromtimestamp(record["received"]),
            payload={
                "server_time": record["server_time"],
                "round_trip": record["round_trip"],
            },
        )
    elif kind == "effect":
        fields.update(name=record["name"], payload=record["payload"])
    elif kind == "checkpoint":
        fields.update(state=record["state"])
    elif kind == "player_add":
        fields.update(
            participant_id=int(record["participant"]),
            payload={"bot": record["bot"]},
        )
    elif kind == "player_end":
        fields.update(
            participant_id=int(record["participant"]),
            reason=record["reason"],
            outcome=record["outcome"],
        )
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
    # it failed. A row another job has saved the ending of keeps it.
    try:
        db.session.query(RealtimeSession).filter(
            RealtimeSession.id == session_id, RealtimeSession.status == "running"
        ).update({"status": "failed", "error": text})
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("Session %s couldn't be marked failed.", session_id)
    try:
        store.end_realtime_session(session_id, FAILED)
    except Exception:
        logger.exception("Session %s couldn't be ended.", session_id)
