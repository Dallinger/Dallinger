"""Heroku web worker."""

import os
import redis


listen = ['high', 'default', 'low']
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
conn = redis.from_url(redis_url)

if __name__ == '__main__':  # pragma: nocover

    # Make sure gevent patches are applied early.
    import gevent.monkey
    gevent.monkey.patch_all()

    # These imports are inside the __main__ block
    # to make sure that we only import from rq_gevent_worker
    # (which has the side effect of applying gevent monkey patches)
    # in the worker process. This way other processes can import the
    # redis connection without that side effect.
    from rq import (
        Queue,
        Connection
    )
    from dallinger.heroku.rq_gevent_worker import GeventWorker as Worker

    from dallinger.config import initialize_experiment_package
    initialize_experiment_package(os.getcwd())

    import logging
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.INFO)

    with Connection(conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()
