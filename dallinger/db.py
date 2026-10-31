"""Create a connection to the database."""

import json
import logging
import math
import os
import random
import sys
import time
from contextlib import contextmanager
from functools import partial, wraps
from typing import NamedTuple, Union

import psycopg2
from psycopg2.extensions import TransactionRollbackError
from redis import RedisError
from rq import Queue
from sqlalchemy import Table, create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.schema import DropTable

from dallinger.config import initialize_experiment_package
from dallinger.redis_utils import connect_to_redis

logger = logging.getLogger(__name__)


def corrected_db_url(db_url):
    # The sqlalchemy dialect name needs to be `postgresql`, not `postgres`
    if db_url.startswith("postgres://"):
        return f"postgresql://{db_url[11:]}"

    return db_url


# create_db_engine argument, environment variable, default, minimum, type.
# Integer minimums are inclusive; float minimums are exclusive.
_POOL_SETTINGS = (
    ("pool_size", "DATABASE_POOL_SIZE", 20, 1, int),
    ("max_overflow", "DATABASE_MAX_OVERFLOW", -1, -1, int),
    ("pool_timeout", "DATABASE_POOL_TIMEOUT", 30, 0, float),
)


def _check_number(name, value, minimum, cast):
    """Return ``value`` if it is a finite ``cast`` that meets ``minimum``.

    ``int`` settings must be at least ``minimum``. ``float`` settings must be
    greater than ``minimum`` and also accept integers. Otherwise raise a
    ``ValueError`` that names ``name``.
    """
    if cast is int:
        valid = isinstance(value, int) and value >= minimum
        no_limit = " (no limit)" if minimum == -1 else ""
        requirement = f"an integer of at least {minimum}{no_limit}"
    else:
        valid = isinstance(value, (int, float)) and minimum < value < math.inf
        requirement = f"a number greater than {minimum}"
    if isinstance(value, bool) or not valid:
        raise ValueError(f"{name} must be {requirement}, not {value!r}.")
    return value


def _env_number(variable, default, minimum, cast):
    """Read ``variable`` as a checked ``cast``, or ``default`` if unset or empty."""
    text = os.environ.get(variable, "").strip()
    if not text:
        return default
    try:
        value = cast(text)
    except ValueError:
        value = text
    return _check_number(variable, value, minimum, cast)


def create_db_engine(db_url, pool_size=None, max_overflow=None, pool_timeout=None):
    """Create a SQLAlchemy engine for ``db_url``.

    By default the pool never makes a request wait for a connection: a gevent
    worker can serve many requests at once, so the pool may grow without limit,
    and connections beyond ``pool_size`` are closed when returned rather than
    kept idle, where they would count against the database's client limit.
    Because overflow is unlimited, a session leak keeps opening connections until
    Postgres or pgbouncer refuses them, rather than hitting a pool timeout.

    Each checkout first pings the connection and replaces it if the server has
    dropped it, for example after pgbouncer or Postgres restarts while the web
    workers keep running.

    Parameters
    ----------
    db_url : str
        Database URL.
    pool_size : int, optional
        Idle connections kept open, at least 1, because SQLAlchemy treats 0 as
        no limit. Defaults to ``DATABASE_POOL_SIZE``, or 20.
    max_overflow : int, optional
        Connections opened beyond ``pool_size`` under load; -1 means no limit.
        Defaults to ``DATABASE_MAX_OVERFLOW``, or -1.
    pool_timeout : float, optional
        Seconds to wait for a connection once ``pool_size + max_overflow`` are
        in use, greater than 0. Defaults to ``DATABASE_POOL_TIMEOUT``, or 30.

    Returns
    -------
    sqlalchemy.engine.Engine
        The new engine.

    Raises
    ------
    ValueError
        If an argument or one of the environment variables is invalid.
    """
    options = {
        "pool_size": pool_size,
        "max_overflow": max_overflow,
        "pool_timeout": pool_timeout,
    }
    for argument, variable, default, minimum, cast in _POOL_SETTINGS:
        if options[argument] is None:
            options[argument] = _env_number(variable, default, minimum, cast)
        else:
            _check_number(argument, options[argument], minimum, cast)
    return create_engine(
        corrected_db_url(db_url),
        pool_pre_ping=True,
        **options,
    )


db_url_default = "postgresql://dallinger:dallinger@localhost/dallinger"
db_url = corrected_db_url(os.environ.get("DATABASE_URL", db_url_default))
engine = create_db_engine(db_url)
logger.debug(f"Using database URL {engine.url.render_as_string()}")
session_factory = sessionmaker(autocommit=False, autoflush=True, bind=engine)
session = scoped_session(session_factory)

Base = declarative_base()
Base.query = session.query_property()
redis_conn = connect_to_redis()

CONTROL_CHANNEL = "dallinger_control"

#: Carries directed sends between processes, and prefixes the frame one arrives
#: in at the browser. The two are different shapes: over redis, an envelope
#: holding its publisher's ``origin`` and a list of ``items``, each naming its
#: recipients, and on the wire to the browser, one item's payload alone.
DIRECT_CHANNEL = "dallinger_direct"

#: Carries a real-time session's views and endings to its players' pages, in
#: the same two shapes as :data:`DIRECT_CHANNEL`, and prefixes their frames.
REALTIME_SESSION_CHANNEL = "dallinger_realtime_session"


def direct_envelope(origin, sends):
    """Return the JSON text of an envelope for :data:`DIRECT_CHANNEL` or
    :data:`REALTIME_SESSION_CHANNEL`.

    :param origin: names the publisher, a string. A web process ignores the
        envelopes it published itself.
    :param sends: dicts, each holding the ``participant_ids`` to send to, as
        strings, the ``scope`` of the pages to send to, or ``None`` for every
        page, and the ``payload`` text
    """
    return json.dumps({"origin": origin, "items": list(sends)})


#: Carries a real-time page's time requests, which the web process answers on
#: the same socket, and the clock measurements the page reports.
TIME_CHANNEL = "dallinger_time"

#: Channels Dallinger owns. A client may not subscribe to one, and may only
#: send frames on :data:`TIME_CHANNEL`, which the web process handles itself.
RESERVED_CHANNELS = frozenset(
    {CONTROL_CHANNEL, DIRECT_CHANNEL, REALTIME_SESSION_CHANNEL, TIME_CHANNEL}
)


def channel_frame(channel, text):
    """Return the websocket frame that carries ``text`` on ``channel``: the
    channel's name, a colon, then the text.
    """
    return "{}:{}".format(channel, text)


db_user_warning = """
*********************************************************
*********************************************************


Dallinger now requires a database user named "dallinger".

Run:

    createuser -P dallinger --createdb

Consult the developer guide for more information.


*********************************************************
*********************************************************

"""


def get_queue(name="default"):
    """Return an rq.Queue with a connection to redis.

    Optional param "name" should be one of:
        - "high"
        - "default"
        - "low"

    as these are the names of the queues workers read from.
    """
    return Queue(name, connection=redis_conn)


def check_connection(timeout_secs=3):
    """Test that postgres is running and that we can connect using the
    configured URI.

    Raises a psycopg2.OperationalError on failure.
    """
    try:
        conn = psycopg2.connect(db_url, connect_timeout=timeout_secs)
    except psycopg2.OperationalError as exc:
        raise Exception(
            f"Failed to connect to Postgres at {db_url}. "
            "Is Postgres running on port 5432?"
        ) from exc

    conn.close()


@contextmanager
def sessions_scope(session_=session, commit=False):
    """Provide a transactional scope around a series of operations."""
    try:
        yield session_
        if commit:
            session_.commit()
            logger.debug("DB session auto-committed as requested")
    except Exception as e:
        # The exception is re-raised to whoever reports it with its traceback
        # (Flask, werkzeug's debugger, RQ, APScheduler or Python itself);
        # logging the traceback here as well printed it twice. If the
        # rollback fails, Python chains its exception to this one.
        logger.debug(
            "Rolling back the database session after %s: %s", type(e).__name__, e
        )
        # This rollback is potentially redundant with the remove call below,
        # depending on how the scoped session is configured, but we'll be
        # explicit here.
        session_.rollback()
        raise e
    finally:
        session_.remove()
        logger.debug("Session complete, db session closed")


def scoped_session_decorator(func):
    """Manage contexts and add debugging to db sessions."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        with sessions_scope():
            # The session used in func comes from the funcs globals, but
            # it will be a proxied thread local var from the session
            # registry, and will therefore be identical to the one returned
            # by the context manager above.
            logger.debug("Running worker %s in scoped DB session", func.__name__)
            return func(*args, **kwargs)

    return wrapper


# By default sqlalchemy does not issue a CASCADE to PostgreSQL
# when dropping tables. This makes init_db fail when tables depend
# on one another. The following code fixes this by instructing the compiler
# to always issue CASCADE when dropping tables.
@compiles(DropTable, "postgresql")
def _compile_drop_table(element, compiler, **kwargs):
    return compiler.visit_drop_table(element) + " CASCADE"


def init_db(drop_all=False, bind=engine):
    """Initialize the database, optionally dropping existing tables.

    Dropping the experiment's own tables also deletes its real-time sessions
    from redis, as :func:`~dallinger.realtime.store.clear_realtime_sessions`
    describes.
    """
    # To create the db structure according to the experiment configuration
    # we need to import the experiment code, so that sqlalchemy has a chance
    # to update its metadata
    initialize_experiment_package(os.getcwd())
    try:
        from dallinger_experiment import experiment  # noqa: F401
    except ImportError:
        pass

    clear_redis = drop_all and bind is engine
    if clear_redis:
        try:
            redis_conn.ping()
        except RedisError:
            logger.error(
                "Could not reach redis to delete the real-time sessions, so "
                "the database was left unchanged. Restore redis and rerun "
                "this command."
            )
            raise

    try:
        if drop_all:
            Base.metadata.drop_all(bind=bind)
        try:
            if clear_redis:
                # Cleared before the tables are recreated, so a new session
                # can't take a reused id and then lose its keys. Imported
                # here because the store imports this module.
                from dallinger.realtime.store import clear_realtime_sessions

                clear_realtime_sessions()
        except RedisError:
            # Fatal because session ids restart at 1 in the new tables, and
            # runners would resume the stale sessions against them.
            logger.error(
                "Could not delete the old real-time sessions from redis after "
                "dropping the database tables, which are recreated empty. "
                "Restore redis and rerun this command before accepting "
                "participants."
            )
            raise
        finally:
            Base.metadata.create_all(bind=bind)
    except OperationalError as err:
        msg = 'password authentication failed for user "dallinger"'
        if msg in str(err):
            sys.stderr.write(db_user_warning)
        raise

    return session


def get_all_mapped_classes():
    """
    Lists the different classes that are mapped with SQLAlchemy.
    Classes are only included if they have at least one row in the database.
    Returns a dictionary, keyed by class names,
    where each value is itself a dictionary with three values:
    ``cls``, the class itself;
    ``table``, the database table within which the class can be found,
    and ``polymorphic_identity``, the string label with which the class is
    identified in the table's ``type`` column. The ``polymorphic_identity`` field
    takes a value of ``None`` if the table does not use polymorphic inheritance.
    """
    classes = {}
    for table in Base.metadata.tables.values():
        if "type" in table.columns:
            # Most Dallinger tables (e.g. Node, Network) have a type column that specifies which class
            # is associated with that database row.
            observed_types = [
                r.type for r in session.query(table.columns.type).distinct().all()
            ]
            mapping = get_polymorphic_mapping(table)
            for type_ in observed_types:
                cls = mapping[type_]
                classes[cls.__name__] = {
                    "cls": cls,
                    "table": table.name,
                    "polymorphic_identity": type_,
                }
        else:
            # Some tables (e.g. Notification) don't have any such column, so we can assume
            # that they have exactly one mapped class.
            if session.query(table.columns.id).count() > 0:
                cls = get_mapped_class(table)
                classes[cls.__name__] = {
                    "cls": cls,
                    "table": table.name,
                    "polymorphic_identity": None,
                }
    return classes


def get_mappers(table: Union[str, Table]):
    if isinstance(table, str):
        table_name = table
    else:
        assert isinstance(table, Table)
        table_name = table.name

    return [
        mapper
        for mapper in Base.registry.mappers
        if table_name in [table.name for table in mapper.tables]
    ]


def get_polymorphic_mapping(table: Union[str, Table]):
    """
    Gets the polymorphic mapping for a given table.
    Returns a dictionary
    where the dictionary keys correspond to polymorphic identities
    (i.e. possible values of the table's ``type`` column)
    and the dictionary values correspond to classes.
    """
    mapping = {}
    for mapper in get_mappers(table):
        name = mapper.polymorphic_identity

        # If we encounter two mappers with the same name, prioritize the one that is defined
        # in the loaded Dallinger experiment
        if name in mapping and mapping[name].__module__ == "dallinger_experiment":
            continue

        mapping[name] = mapper.class_
    return mapping


def get_mapped_classes(table: Union[str, Table]):
    """
    Returns a list of classes that map to the provided table.
    """
    return [
        mapper.class_
        for mapper in Base.registry.mappers
        if mapper in get_mappers(table)
    ]


def get_mapped_class(table: Union[str, Table]):
    """
    Returns the single class that maps to the provided table.
    Throws an ``AssertionError`` if there is not exactly one such class.
    This function is therefore only intended for tables that do not implement
    polymorphic identities, i.e. they do not include a ``type`` column.
    An example is the Notification table.
    """
    mappers = get_mapped_classes(table)
    assert len(mappers) == 1
    return mappers[0]


def serialized(func):
    """Run a function within a db transaction using SERIALIZABLE isolation.

    With this isolation level, committing will fail if this transaction
    read data that was since modified by another transaction. So we need
    to handle that case and retry the transaction.
    """

    @wraps(func)
    def wrapper(*args, **kw):
        attempts = 100
        session.remove()
        while attempts > 0:
            try:
                session.connection(
                    execution_options={"isolation_level": "SERIALIZABLE"}
                )
                result = func(*args, **kw)
                session.commit()
                return result
            except OperationalError as exc:
                session.rollback()
                if isinstance(exc.orig, TransactionRollbackError):
                    if attempts > 0:
                        attempts -= 1
                    else:
                        raise Exception(
                            "Could not commit serialized transaction "
                            "after 100 attempts."
                        )
                else:
                    raise
            finally:
                session.remove()
            time.sleep(random.expovariate(0.5))

    return wrapper


class _Waiting(NamedTuple):
    transaction: object
    callback: object
    description: object


def run_after_commit(callback, description=None):
    """Call ``callback`` with no arguments once the session's transaction
    commits. It's never called if the transaction, or the savepoint it was
    added in, rolls back. A callback that raises is logged, and the rest
    still run.

    A callback still waiting when its transaction ends without a commit, as
    when the session is closed, is dropped and logged. Passing a
    ``description`` names the callback in the log, which is then an error
    rather than a warning, for a callback whose loss matters.
    """
    current = session()
    # Begins the transaction if none has begun.
    current.connection()
    transaction = current.get_nested_transaction() or current.get_transaction()
    session.info.setdefault("after_commit", []).append(
        _Waiting(transaction, callback, description)
    )


def queue_message(channel, message):
    """Publish ``message`` to the redis ``channel`` once the session's
    transaction commits, as :func:`run_after_commit` does.
    """
    logger.debug("Enqueueing message to {}: {}".format(channel, message))
    run_after_commit(partial(_publish, channel, message))


def _publish(channel, message):
    logger.debug("Publishing message to {}: {}".format(channel, message))
    redis_conn.publish(channel, message)


@event.listens_for(Session, "after_commit")
def after_commit(session):
    # after_commit also fires when a savepoint is released.
    if session.in_nested_transaction():
        return
    for waiting in session.info.pop("after_commit", ()):
        # An exception here would leave the session unusable, even by
        # rollback, since SQLAlchemy closes the transaction only after this
        # event.
        try:
            waiting.callback()
        except Exception:
            logger.exception("A callback run after a commit failed.")


@event.listens_for(Session, "after_rollback")
def after_rollback(session):
    # A rollback of the outermost transaction fires this before
    # after_transaction_end, and a savepoint's fires after_soft_rollback.
    if not session.in_nested_transaction():
        session.info["after_commit"] = []


@event.listens_for(Session, "after_soft_rollback")
def after_soft_rollback(session, previous_transaction):
    session.info["after_commit"] = [
        waiting
        for waiting in session.info.get("after_commit", ())
        if not _within(waiting.transaction, previous_transaction)
    ]


def _within(transaction, outer):
    while transaction is not None:
        if transaction is outer:
            return True
        transaction = transaction.parent
    return False


@event.listens_for(Session, "after_transaction_end")
def after_transaction_end(session, transaction):
    waiting = session.info.get("after_commit")
    if transaction.parent is None and waiting:
        described = [each.description for each in waiting if each.description]
        message = (
            "Dropped {} callbacks waiting for a commit, because their "
            "transaction ended without one".format(len(waiting))
        )
        if described:
            logger.error("%s: %s.", message, "; ".join(described))
        else:
            logger.warning("%s.", message)
        session.info["after_commit"] = []
