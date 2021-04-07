import os
import redis

from urllib.parse import urlparse


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
