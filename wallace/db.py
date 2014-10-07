from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
import os

# create the connection to the database
if "DATABASE_URL" in os.environ:
    db_url = os.environ["DATABASE_URL"]
else:
    db_url = "sqlite:///wallace.db"

engine = create_engine(db_url)
db = scoped_session(sessionmaker(autoflush=True, bind=engine))

Base = declarative_base()
Base.query = db.query_property()


def init_db(drop_all=False):
    """Initialize the database, optionally dropping existing tables."""
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return db
