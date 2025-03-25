"""Create a connection to the database."""

import logging
import os
import random
import sys
import time
from contextlib import contextmanager
from functools import wraps
from typing import Union

import psycopg2
from psycopg2.extensions import TransactionRollbackError
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


def create_db_engine(db_url, pool_size=1000):
    return create_engine(corrected_db_url(db_url), pool_size=pool_size)


db_url_default = "postgresql://dallinger:dallinger@localhost/dallinger"
db_url = corrected_db_url(os.environ.get("DATABASE_URL", db_url_default))
engine = create_db_engine(db_url)
logger.debug(f"Using database URL {engine.url.render_as_string()}")
session_factory = sessionmaker(autocommit=False, autoflush=True, bind=engine)
session = scoped_session(session_factory)

Base = declarative_base()
Base.query = session.query_property()
redis_conn = connect_to_redis()

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
def sessions_scope(local_session, commit=False):
    """Provide a transactional scope around a series of operations."""
    try:
        yield local_session
        if commit:
            local_session.commit()
            logger.debug("DB session auto-committed as requested")
    except Exception as e:
        # We log the exception before re-raising it, in case the rollback also
        # fails
        logger.exception("Exception during scoped worker transaction, " "rolling back.")
        # This rollback is potentially redundant with the remove call below,
        # depending on how the scoped session is configured, but we'll be
        # explicit here.
        local_session.rollback()
        raise e
    finally:
        local_session.remove()
        logger.debug("Session complete, db session closed")


def scoped_session_decorator(func):
    """Manage contexts and add debugging to db sessions."""

    @wraps(func)
    def wrapper(*args, **kwargs):
        with sessions_scope(session):
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
    """Initialize the database, optionally dropping existing tables."""
    # To create the db structure according to the experiment configuration
    # we need to import the experiment code, so that sqlalchemy has a chance
    # to update its metadata
    initialize_experiment_package(os.getcwd())
    try:
        from dallinger_experiment import experiment  # noqa: F401
    except ImportError:
        pass

    try:
        if drop_all:
            Base.metadata.drop_all(bind=bind)
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


# Reset outbox when session begins
@event.listens_for(Session, "after_begin")
def after_begin(session, transaction, connection):
    session.info["outbox"] = []


# Reset outbox after rollback
@event.listens_for(Session, "after_soft_rollback")
def after_soft_rollback(session, previous_transaction):
    session.info["outbox"] = []


def queue_message(channel, message):
    logger.debug("Enqueueing message to {}: {}".format(channel, message))
    if "outbox" not in session.info:
        session.info["outbox"] = []
    session.info["outbox"].append((channel, message))


# Publish messages to redis after commit
@event.listens_for(Session, "after_commit")
def after_commit(session):
    for channel, message in session.info.get("outbox", ()):
        logger.debug("Publishing message to {}: {}".format(channel, message))
        redis_conn.publish(channel, message)
