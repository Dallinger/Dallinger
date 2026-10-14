import threading

import pytest
import redis

from dallinger import redis_utils
from dallinger.redis_utils import connect_to_redis


def test_connections_wait_for_a_free_slot_instead_of_failing(monkeypatch):
    monkeypatch.setattr(redis_utils, "MAX_CONNECTIONS", 1)
    # The client owns its pool and closes it when garbage-collected.
    client = connect_to_redis("redis://localhost:6379")
    try:
        try:
            client.ping()
        except redis.ConnectionError:
            pytest.skip("Redis is not running")
        pool = client.connection_pool
        held = pool.get_connection()
        threading.Timer(0.2, pool.release, args=[held]).start()

        assert pool.get_connection() is held
    finally:
        client.close()


@pytest.mark.parametrize("patched", [False, True])
def test_pool_queue_matches_gevent_patching(monkeypatch, patched):
    import gevent.monkey
    import gevent.queue

    monkeypatch.setattr(gevent.monkey, "is_module_patched", lambda name: patched)
    pool = connect_to_redis("redis://localhost:6379").connection_pool
    assert (pool.queue_class is gevent.queue.LifoQueue) is patched


def test_secure_connections_skip_certificate_checks():
    pool = connect_to_redis("rediss://localhost:6379").connection_pool
    assert pool.connection_class is redis.SSLConnection
    assert pool.connection_kwargs["ssl_cert_reqs"] is None
