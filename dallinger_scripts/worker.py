"""Heroku web worker."""
listen = ["high", "default", "low"]


def main():
    import gevent.monkey

    gevent.monkey.patch_all()
    from gevent.queue import LifoQueue

    # These imports are inside the __main__ block
    # to make sure that we only import from rq_gevent_worker
    # (which has the side effect of applying gevent monkey patches)
    # in the worker process. This way other processes can import the
    # redis connection without that side effect.
    import logging
    import os
    from redis import BlockingConnectionPool, StrictRedis
    from rq import Queue, Connection
    from six.moves.urllib.parse import urlparse
    from dallinger.heroku.rq_gevent_worker import GeventWorker as Worker
    from dallinger.config import initialize_experiment_package

    initialize_experiment_package(os.getcwd())

    logging.basicConfig(format="%(asctime)s %(message)s", level=logging.DEBUG)
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    # Specify queue class for improved performance with gevent.
    # see http://carsonip.me/posts/10x-faster-python-gevent-redis-connection-pool/

    connection_args = {
        "url": redis_url,
        "queue_class": LifoQueue,
    }
    # Since we are generally running on Heroku, and configuring SSL certificates
    # is challenging, we disable cert requirements on secure connections.
    if urlparse(redis_url).scheme == "rediss":
        connection_args["ssl_cert_reqs"] = None
    redis_pool = BlockingConnectionPool.from_url(**connection_args)
    redis_conn = StrictRedis(connection_pool=redis_pool)

    with Connection(redis_conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()


if __name__ == "__main__":  # pragma: nocover
    main()
