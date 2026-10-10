import threading

import redis

from dallinger import redis_utils
from dallinger.redis_utils import connect_to_redis


def test_connections_wait_for_a_free_slot_instead_of_failing(monkeypatch):
    monkeypatch.setattr(redis_utils, "MAX_CONNECTIONS", 1)
    pool = connect_to_redis("redis://localhost:6379").connection_pool
    held = pool.get_connection()
    threading.Timer(0.2, pool.release, args=[held]).start()

    assert pool.get_connection() is held
    pool.disconnect()


def test_secure_connections_skip_certificate_checks():
    pool = connect_to_redis("rediss://localhost:6379").connection_pool
    assert pool.connection_class is redis.SSLConnection
    assert pool.connection_kwargs["ssl_cert_reqs"] is None
