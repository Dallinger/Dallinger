listen = ["high", "default", "low"]


def main():
    import gevent.monkey

    gevent.monkey.patch_all()
    # These imports are inside the __main__ block
    # to make sure that we only import from rq_gevent_worker
    # (which has the side effect of applying gevent monkey patches)
    # in the worker process. This way other processes can import the
    # redis connection without that side effect.
    import logging
    import os
    from urllib.parse import urlparse

    from gevent.queue import LifoQueue
    from redis import BlockingConnectionPool, StrictRedis
    from rq import Queue

    from dallinger.config import LOG_LEVELS, get_config, initialize_experiment_package
    from dallinger.heroku.rq_gevent_worker import GeventWorker as Worker
    from dallinger.utils import attach_json_logger

    initialize_experiment_package(os.getcwd())

    config = get_config(load=True)
    log_level = LOG_LEVELS[config.get("loglevel_worker")]
    logging.basicConfig(format="%(asctime)s %(message)s", level=log_level)
    attach_json_logger(logging.getLogger())
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

    worker = Worker(
        [Queue(name, connection=redis_conn) for name in listen],
        connection=redis_conn,
        log_job_description=False,
    )
    worker.log_result_lifespan = False
    # Default to log.warn because rq logs extremely verbosely at the info
    # level
    worker.log.info = worker.log.debug

    supervisor = None
    if has_realtime_games():
        import signal

        import gevent

        from dallinger.realtime.supervisor import RunnerSupervisor

        supervisor = RunnerSupervisor()
        # gevent runs every handler registered for a signal, so these run
        # beside the ones the worker registers.
        for signum in (signal.SIGTERM, signal.SIGINT):
            gevent.signal_handler(signum, supervisor.stop)
        supervisor.start()
    try:
        worker.work(logging_level=log_level)
    finally:
        if supervisor is not None:
            supervisor.stop()
            # A container's other processes are killed when its first one
            # exits, so the runner must give up its sessions first.
            supervisor.join()


def has_realtime_games():
    """Whether the experiment has game types, so the worker should keep a
    runner going. An experiment that can't be loaded is logged, and has none.
    """
    import logging

    from dallinger import experiment

    try:
        return bool(experiment.load().realtime_games)
    except Exception:
        logging.getLogger(__name__).exception(
            "Couldn't load the experiment, so no real-time runner is started."
        )
        return False


if __name__ == "__main__":  # pragma: nocover
    main()
