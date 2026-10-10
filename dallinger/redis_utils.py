import os
from urllib.parse import urlparse

import redis

# A gevent web worker can have many requests using Redis at once. redis-py's
# default pool fails immediately beyond 100 connections; this pool makes callers
# wait for a free connection instead, and only fails after the timeout.
MAX_CONNECTIONS = 1000
CONNECTION_TIMEOUT_SECS = 20


def connect_to_redis(url=None):
    """Return a connection to Redis.

    If a URL is supplied, it will be used, otherwise an environment variable
    is checked before falling back to a default.

    Since we are generally running on Heroku, and configuring SSL certificates
    is challenging, we disable cert requirements on secure connections.
    """
    redis_url = url or os.getenv("REDIS_URL", "redis://localhost:6379")
    connection_args = {
        "max_connections": MAX_CONNECTIONS,
        "timeout": CONNECTION_TIMEOUT_SECS,
    }
    if urlparse(redis_url).scheme == "rediss":
        connection_args["ssl_cert_reqs"] = None

    pool = redis.BlockingConnectionPool.from_url(redis_url, **connection_args)
    client = redis.Redis(connection_pool=pool)
    client.auto_close_connection_pool = True
    return client
