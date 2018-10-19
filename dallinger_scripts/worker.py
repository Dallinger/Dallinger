"""Heroku web worker."""
# Make sure gevent patches are applied early.
import os

listen = ['high', 'default', 'low']


def main():
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
    from dallinger.db import redis_conn
    from dallinger.heroku.rq_gevent_worker import GeventWorker as Worker

    from dallinger.config import initialize_experiment_package
    initialize_experiment_package(os.getcwd())

    import logging
    logging.basicConfig(format='%(asctime)s %(message)s', level=logging.DEBUG)

    with Connection(redis_conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()


if __name__ == '__main__':  # pragma: nocover
    main()
