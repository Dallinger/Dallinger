import warnings

from dallinger.db import redis_conn

warnings.warn(
    "Importing from heroku.worker is deprecated and may cause errors."
    "The redis `conn` should be imported from `dallinger.db.redis_conn`",
    DeprecationWarning,
)

conn = redis_conn
