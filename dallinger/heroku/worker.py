import warnings
from dallinger.db import redis_conn
warnings.warn(
    u"Importing from heroku.worker is deprecated and may cause errors."
    u"The redis `conn` should be imported from `dallinger.db.redis_conn`",
    DeprecationWarning
)

conn = redis_conn
