from dallinger.db import redis_conn


class RedisTally(object):
    _key = "num_recruited"

    def __init__(self):
        redis_conn.set(self._key, 0)

    def increment(self, count):
        redis_conn.incr(self._key, count)

    @property
    def current(self):
        return int(redis_conn.get(self._key))
