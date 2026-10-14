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

    Each client gets its own waiting pool of up to ``MAX_CONNECTIONS``
    connections. When they are all in use, a caller waits up to
    ``CONNECTION_TIMEOUT_SECS`` for one to be released before redis-py raises
    ``ConnectionError``.

    The pool uses gevent's queue if ``threading`` is already monkey-patched
    when this function is called. ``dallinger.db`` calls it at import, so
    ``gevent.monkey.patch_all()`` must run before ``dallinger.db`` is imported.

    Since we are generally running on Heroku, and configuring SSL certificates
    is challenging, we disable cert requirements on secure connections.
    """
    redis_url = url or os.getenv("REDIS_URL", "redis://localhost:6379")
    connection_args = {
        "max_connections": MAX_CONNECTIONS,
        "timeout": CONNECTION_TIMEOUT_SECS,
    }
    import gevent.monkey

    if gevent.monkey.is_module_patched("threading"):
        import gevent.queue

        # See http://carsonip.me/posts/10x-faster-python-gevent-redis-connection-pool/
        connection_args["queue_class"] = gevent.queue.LifoQueue
    if urlparse(redis_url).scheme == "rediss":
        connection_args["ssl_cert_reqs"] = None

    pool = redis.BlockingConnectionPool.from_url(redis_url, **connection_args)
    return redis.Redis.from_pool(pool)
