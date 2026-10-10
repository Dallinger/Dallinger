import redis

from dallinger.redis_utils import connect_to_redis


def test_connections_wait_for_a_free_slot_instead_of_failing():
    pool = connect_to_redis("redis://localhost:6379").connection_pool
    assert isinstance(pool, redis.BlockingConnectionPool)
    assert pool.max_connections > 100


def test_secure_connections_skip_certificate_checks():
    pool = connect_to_redis("rediss://localhost:6379").connection_pool
    assert pool.connection_class is redis.SSLConnection
    assert pool.connection_kwargs["ssl_cert_reqs"] is None
