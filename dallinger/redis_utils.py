import os
from urllib.parse import urlparse

import redis
from rq import Queue

from dallinger.db import redis_conn


def connect_to_redis(url=None):
    """Return a connection to Redis.

    If a URL is supplied, it will be used, otherwise an environment variable
    is checked before falling back to a default.

    Since we are generally running on Heroku, and configuring SSL certificates
    is challenging, we disable cert requirements on secure connections.
    """
    redis_url = url or os.getenv("REDIS_URL", "redis://localhost:6379")
    connection_args = {"url": redis_url}
    if urlparse(redis_url).scheme == "rediss":
        connection_args["ssl_cert_reqs"] = None

    return redis.from_url(**connection_args)


def _get_queue(name="default"):
    # Connect to Redis Queue
    return Queue(name, connection=redis_conn)


class RedisStore(object):
    """A wrapper around redis, to handle value decoding on retrieval,
    and easy cleanup of all managed keys via a prefix applied to all
    stored key/value pairs.
    """

    def __init__(self):
        self._redis = redis_conn
        self._prefix = self.__class__.__name__

    def set(self, key, value):
        """Add a prefix to the key, then store the key/value pair in redis."""
        self._redis.set(self._prefixed(key), value)

    def get(self, key):
        """Retrieve the value from redis and decode it."""
        raw = self._redis.get(self._prefixed(key))
        if raw is not None:
            return raw.decode("utf-8")

    def clear(self):
        """Remove any key that starts with our prefix."""
        for key in self._redis.keys():
            key_decoded = key.decode("utf-8")
            if key_decoded.startswith(self._prefix):
                self._redis.delete(key)

    def _prefixed(self, key):
        return "{}:{}".format(self._prefix, key)
