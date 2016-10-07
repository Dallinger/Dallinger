"""Create a connection to the database."""

from contextlib import contextmanager
from functools import wraps
import logging
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base


logger = logging.getLogger('dallinger.db')

db_url_default = "postgresql://postgres@localhost/dallinger"
db_url = os.environ.get("DATABASE_URL", db_url_default)
engine = create_engine(db_url, pool_size=1000)
session = scoped_session(sessionmaker(autocommit=False,
                                      autoflush=True,
                                      bind=engine))

Base = declarative_base()
Base.query = session.query_property()


@contextmanager
def sessions_scope(local_session, commit=False):
    """Provide a transactional scope around a series of operations."""
    try:
        yield local_session
        if commit:
            local_session.commit()
            logger.debug('DB session auto-committed as requested')
    except:
        # We log the exception before re-raising it, in case the rollback also
        # fails
        logger.exception('Exception during scoped worker transaction, '
                         'rolling back.')
        # This rollback is potentially redundant with the remove call below,
        # depending on how the scoped session is configured, but we'll be
        # explicit here.
        local_session.rollback()
        raise
    finally:
        local_session.remove()
        logger.debug('Session complete, db session closed')


def scoped_session_decorator(func):
    """Manage contexts and add debugging to psiTurk sessions."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        from dallinger.db import session as dallinger_session
        with sessions_scope(dallinger_session) as session:
            from psiturk.db import db_session as psi_session
            with sessions_scope(psi_session) as session_psiturk:
                # The sessions used in func come from the funcs globals, but
                # they will be proxied thread locals vars from the session
                # registry, and will therefore be identical to those returned
                # by the context managers above.
                logger.debug('Running worker %s in scoped DB sessions',
                             func.__name__)
                return func(*args, **kwargs)
    return wrapper


def init_db(drop_all=False):
    """Initialize the database, optionally dropping existing tables."""
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    return session
