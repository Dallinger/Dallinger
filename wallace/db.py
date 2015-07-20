"""Create a connection to the database."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import os

db_url = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost/wallace")
engine = create_engine(db_url, pool_size=100)
Session = scoped_session(sessionmaker(autoflush=True, bind=engine))

Base = declarative_base()
Base.query = Session.query_property()

def get_session():
    return Session

def init_db(drop_all=False):
    """Initialize the database, optionally dropping existing tables."""
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    return Session
