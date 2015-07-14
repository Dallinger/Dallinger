"""Create a connection to the database."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import os

db_url = os.environ.get("DATABASE_URL", "postgresql://postgres@localhost/wallace")
engine = create_engine(db_url)
Session = scoped_session(sessionmaker(autoflush=True, bind=engine))

Base = declarative_base()
Base.query = Session.query_property()


def init_db(drop_all=False):
    """Initialize the database, optionally dropping existing tables."""
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    if os.environ["wallace_init"] is not "true":
        os.environ["wallace_init"] = "true"
        Base.metadata.create_all(bind=engine)

    return Session
