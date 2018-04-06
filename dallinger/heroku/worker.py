"""Heroku web worker."""

from future.builtins import map
import os
import redis


listen = ['high', 'default', 'low']
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
conn = redis.from_url(redis_url, decode_responses=True, charset='utf-8')

if __name__ == '__main__':  # pragma: nocover

    # These imports are inside the __main__ block
    # to make sure that we only import from rq_gevent_worker
    # (which has the side effect of applying gevent monkey patches)
    # in the worker process. This way other processes can import the
    # redis connection without that side effect.
    from rq import (
        Queue,
        Connection
    )
    try:
        from rq_gevent_worker import GeventWorker as Worker
    except ImportError:
        from rq import Worker

    import logging
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

    with Connection(conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()
