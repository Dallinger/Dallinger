"""Heroku web worker."""
listen = ['high', 'default', 'low']


def main():
    import gevent.monkey
    gevent.monkey.patch_all()
    from gevent.queue import LifoQueue

    # These imports are inside the __main__ block
    # to make sure that we only import from rq_gevent_worker
    # (which has the side effect of applying gevent monkey patches)
    # in the worker process. This way other processes can import the
    # redis connection without that side effect.
    import os
    from redis import BlockingConnectionPool, StrictRedis
    from rq import (
        Queue,
        Connection
    )
    from dallinger.heroku.rq_gevent_worker import GeventWorker as Worker

    from dallinger.config import initialize_experiment_package
    initialize_experiment_package(os.getcwd())

    import logging
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)
    redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    # Specify queue class for improved performance with gevent.
    # see http://carsonip.me/posts/10x-faster-python-gevent-redis-connection-pool/
    redis_pool = BlockingConnectionPool.from_url(redis_url,
                                                 queue_class=LifoQueue)
    redis_conn = StrictRedis(connection_pool=redis_pool)

    with Connection(redis_conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()


if __name__ == '__main__':  # pragma: nocover
    main()
