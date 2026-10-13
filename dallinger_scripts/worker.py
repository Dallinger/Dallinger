listen = ["high", "default", "low"]

# Applies until the config is loaded, unless the environment sets
# worker_startup_timeout; keep in step with global_config_defaults.txt.
DEFAULT_STARTUP_TIMEOUT = 120


def _checked_startup_timeout(value):
    """Return ``value`` as whole seconds, or the default if it isn't 0 or more."""
    import sys

    try:
        timeout = int(value)
    except ValueError:
        timeout = -1
    if timeout < 0:
        print(
            f"Invalid worker_startup_timeout {value!r}: "
            "expected a whole number of seconds, 0 or more.",
            file=sys.stderr,
        )
        return DEFAULT_STARTUP_TIMEOUT
    return timeout


def _startup_timeout_from_environment():
    """Return ``worker_startup_timeout`` from the environment, or the default."""
    import os

    value = os.environ.get("worker_startup_timeout")
    if value is None:
        return DEFAULT_STARTUP_TIMEOUT
    return _checked_startup_timeout(value)


def _exit_unless_registered_within(timeout, started):
    """Return a greenlet that ends the process unless it is killed in time.

    It fires ``timeout`` seconds after ``started``, a ``time.monotonic()``
    value, or at once if that is already past. Returns ``None`` if
    ``timeout`` is 0.

    ``GeventWorker.register_birth`` kills it, so only a worker whose start-up
    hangs exits, and Docker or Heroku then restarts it. It is a timer in the
    gevent hub, so it can't fire if start-up blocks without yielding to
    gevent (a blocking C call, an unpatched system call or a CPU-bound loop).
    A watchdog thread or signal doesn't work here: a second thread makes the
    fork in Dallinger's import-time ``script --help`` probe
    (``dallinger.command_line.docker``) hang, and a container's PID 1 ignores
    SIGALRM.
    """
    import time

    import gevent

    if timeout == 0:
        return None

    def exit_unregistered():
        import os
        import sys

        from gevent.util import print_run_info

        print(
            f"Worker hasn't registered with RQ within {timeout} s; exiting.",
            file=sys.stderr,
        )
        print_run_info(file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)

    remaining = max(0, started + timeout - time.monotonic())
    return gevent.spawn_later(remaining, exit_unregistered)


def main():
    import time

    started = time.monotonic()

    import gevent.monkey

    gevent.monkey.patch_all()
    startup_timeout = _startup_timeout_from_environment()
    startup_watchdog = _exit_unless_registered_within(startup_timeout, started)
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

    from dallinger.config import get_config, initialize_experiment_package
    from dallinger.heroku.rq_gevent_worker import GeventWorker as Worker
    from dallinger.utils import attach_json_logger

    initialize_experiment_package(os.getcwd())

    config = get_config(load=True)

    LOG_LEVELS = [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    ]
    LOG_LEVEL = LOG_LEVELS[config.get("loglevel_worker")]
    logging.basicConfig(
        format="%(asctime)s %(message)s",
        level=LOG_LEVEL,
    )
    attach_json_logger(logging.getLogger())

    configured_timeout = _checked_startup_timeout(config.get("worker_startup_timeout"))
    if configured_timeout != startup_timeout:
        if startup_watchdog is not None:
            startup_watchdog.kill()
        startup_timeout = configured_timeout
        startup_watchdog = _exit_unless_registered_within(startup_timeout, started)
    if startup_watchdog is not None:
        logging.getLogger(__name__).warning(
            "Worker will exit if it hasn't registered with RQ within %s s",
            startup_timeout,
        )

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
        startup_watchdog=startup_watchdog,
    )
    worker.log_result_lifespan = False
    # Default to log.warn because rq logs extremely verbosely at the info
    # level
    worker.log.info = worker.log.debug
    worker.work(logging_level=LOG_LEVEL)


if __name__ == "__main__":  # pragma: nocover
    main()
