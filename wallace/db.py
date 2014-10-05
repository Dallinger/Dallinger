from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.schema import CreateSchema
import os

# create the connection to the database
engine = create_engine(os.environ["DATABASE_URL"])
try:
    engine.execute(CreateSchema('wallace'))
except Exception, e:
    pass

db = scoped_session(sessionmaker(autoflush=True, bind=engine))

Base = declarative_base()
Base.query = db.query_property()


def init_db(drop_all=False):
    """Initialize the database, optionally dropping existing tables."""
    if drop_all:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.schema = 'wallace'
    Base.metadata.create_all(bind=engine)
    return db
