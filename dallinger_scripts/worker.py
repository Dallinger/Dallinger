listen = ["high", "default", "low"]
# CPU-heavy counterparts of ``listen``, in the same priority order.
cpu_listen = ["cpu_high", "cpu", "cpu_low"]
CPU_WORKER_COMMAND = ("dallinger_heroku_worker", "--cpu")
DEFAULT_GREENLETS_PER_PROCESS = 20
# Applies until the config is loaded, unless the environment sets
# worker_startup_timeout; keep in step with global_config_defaults.txt.
DEFAULT_STARTUP_TIMEOUT = 120


def worker_options(config, cpu=False):
    """Return the RQ worker's keyword arguments and Redis pool size.

    A CPU worker runs one job at a time. In a gevent worker, each greenlet
    can hold a Redis connection while RQ also uses some, so the connection
    pool needs headroom above the greenlet count.
    """
    worker_kwargs = {"log_job_description": False}
    if cpu:
        return worker_kwargs, 50
    pool_size = config.get(
        "worker_greenlets_per_process", DEFAULT_GREENLETS_PER_PROCESS
    )
    worker_kwargs["pool_size"] = pool_size
    return worker_kwargs, max(50, pool_size + 10)


def worker_queues(config, cpu=False):
    """Return the names of the queues a worker takes jobs from, in order.

    A CPU worker takes jobs only from the CPU queues, ``cpu_high``, ``cpu``
    and ``cpu_low``, in that order. Other workers take them too, after their
    other queues, unless ``cpu_processes_per_worker`` starts CPU workers to
    do it.
    """
    if cpu:
        return list(cpu_listen)
    if config.get("cpu_processes_per_worker", 0) > 0:
        return list(listen)
    return [*listen, *cpu_listen]


def _checked_startup_timeout(value):
    """Return ``value`` as whole seconds, or the default if it isn't 0 or more."""
    import sys

    try:
        timeout = int(value)
    except (TypeError, ValueError):
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


class _AlarmWatchdog:
    """Call ``callback`` with the interrupted frame after ``seconds``, using
    ``SIGALRM``, unless :meth:`kill` is called first."""

    def __init__(self, seconds, callback):
        import math
        import signal

        signal.signal(signal.SIGALRM, lambda signum, frame: callback(frame))
        signal.alarm(max(1, math.ceil(seconds)))

    def kill(self, block=False):
        import signal

        signal.alarm(0)


def _exit_unless_registered_within(timeout, started, cpu=False):
    """Return a watchdog that ends the process unless it is killed in time.

    It fires ``timeout`` seconds after ``started``, a ``time.monotonic()``
    value, or at once if that is already past. Returns ``None`` if
    ``timeout`` is 0.

    The worker's ``register_birth`` kills it, so only a worker whose start-up
    hangs exits, and Docker, Heroku or the worker that started a CPU worker
    then restarts it. In a gevent worker it is a timer in the gevent hub, so
    it can't fire if start-up blocks without yielding to gevent (a blocking C
    call, an unpatched system call or a CPU-bound loop). A watchdog thread or
    signal doesn't work there: a second thread makes the fork in Dallinger's
    import-time ``script --help`` probe (``dallinger.command_line.docker``)
    hang, and a container's PID 1 ignores SIGALRM. A CPU worker
    (``cpu=True``) doesn't run gevent and is never PID 1, so it uses SIGALRM.
    """
    import time

    if timeout == 0:
        return None

    def exit_unregistered(frame=None):
        import os
        import sys
        import traceback

        print(
            f"Worker hasn't registered with RQ within {timeout} s; exiting. "
            "Raise worker_startup_timeout if start-up is legitimately slower.",
            file=sys.stderr,
        )
        if cpu:
            traceback.print_stack(frame, file=sys.stderr)
        else:
            from gevent.util import print_run_info

            print_run_info(file=sys.stderr)
        sys.stderr.flush()
        os._exit(1)

    remaining = max(0, started + timeout - time.monotonic())
    if cpu:
        return _AlarmWatchdog(remaining, exit_unregistered)
    import gevent

    return gevent.spawn_later(remaining, exit_unregistered)


def main(argv=None):
    """Run a worker.

    With ``--cpu``, run a CPU worker: it takes jobs from the CPU queues one
    at a time, each in a process of its own, so a job that computes for long
    can't hold up other jobs and still stops at its timeout. It doesn't use
    gevent, and starts no real-time runner or CPU workers of its own.
    """
    import argparse
    import time

    started = time.monotonic()
    parser = argparse.ArgumentParser(prog="dallinger_heroku_worker")
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Run jobs from the CPU queues, one at a time.",
    )
    cpu = parser.parse_args(argv).cpu

    if not cpu:
        import gevent.monkey

        gevent.monkey.patch_all()
    startup_timeout = _startup_timeout_from_environment()
    startup_watchdog = _exit_unless_registered_within(startup_timeout, started, cpu)
    # These imports are inside the __main__ block
    # to make sure that we only import from rq_gevent_worker
    # (which has the side effect of applying gevent monkey patches)
    # in the worker process. This way other processes can import the
    # redis connection without that side effect.
    # tests/test_rq_gevent_worker.py mirrors these imports; keep it in sync.
    import logging
    import os
    from urllib.parse import urlparse

    from redis import BlockingConnectionPool, StrictRedis
    from rq import Queue

    from dallinger import dev_logging
    from dallinger.config import LOG_LEVELS, get_config, initialize_experiment_package
    from dallinger.utils import attach_json_logger

    if cpu:
        from dallinger.heroku.rq_cpu_worker import CPUWorker as Worker
    else:
        from dallinger.heroku.rq_gevent_worker import GeventWorker as Worker

    initialize_experiment_package(os.getcwd())

    config = get_config(load=True)
    log_level = LOG_LEVELS[config.get("loglevel_worker")]
    if not dev_logging.configure_from_environment(log_level):
        logging.basicConfig(format="%(asctime)s %(message)s", level=log_level)
    attach_json_logger(logging.getLogger())
    worker_kwargs, max_connections = worker_options(config, cpu=cpu)

    # The environment overrides config files, so an env value was already checked.
    if "worker_startup_timeout" not in os.environ:
        configured_timeout = _checked_startup_timeout(
            config.get("worker_startup_timeout")
        )
    else:
        configured_timeout = startup_timeout
    if configured_timeout != startup_timeout:
        if startup_watchdog is not None:
            startup_watchdog.kill()
        startup_timeout = configured_timeout
        startup_watchdog = _exit_unless_registered_within(startup_timeout, started, cpu)
    if startup_watchdog is not None:
        logging.getLogger(__name__).debug(
            "Worker will exit if it hasn't registered with RQ within %s s",
            startup_timeout,
        )

    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    connection_args = {"url": redis_url, "max_connections": max_connections}
    if not cpu:
        from gevent.queue import LifoQueue

        # Specify queue class for improved performance with gevent.
        # see http://carsonip.me/posts/10x-faster-python-gevent-redis-connection-pool/
        connection_args["queue_class"] = LifoQueue
    # Since we are generally running on Heroku, and configuring SSL certificates
    # is challenging, we disable cert requirements on secure connections.
    if urlparse(redis_url).scheme == "rediss":
        connection_args["ssl_cert_reqs"] = None
    redis_pool = BlockingConnectionPool.from_url(**connection_args)
    redis_conn = StrictRedis(connection_pool=redis_pool)

    worker = Worker(
        [Queue(name, connection=redis_conn) for name in worker_queues(config, cpu)],
        connection=redis_conn,
        startup_watchdog=startup_watchdog,
        **worker_kwargs,
    )
    worker.log_result_lifespan = False
    # Default to log.warn because rq logs extremely verbosely at the info
    # level
    worker.log.info = worker.log.debug

    supervisors = [] if cpu else start_supervisors(config)
    try:
        worker.work(logging_level=log_level)
    finally:
        for supervisor in supervisors:
            supervisor.stop()
        # A container's other processes are killed when its first one exits,
        # so the runner must give up its sessions, and CPU workers finish
        # their jobs, first.
        for supervisor in supervisors:
            supervisor.join()


def start_supervisors(config):
    """Start keeping this worker's child processes going, and return their
    :class:`~dallinger.realtime.supervisor.RunnerSupervisor` objects.

    The children are a real-time runner, if the experiment has game types,
    and ``cpu_processes_per_worker`` CPU workers. ``SIGTERM`` and ``SIGINT``
    stop the supervisors and their children.
    """
    import signal

    import gevent

    from dallinger.realtime.supervisor import RunnerSupervisor

    supervisors = [
        RunnerSupervisor(CPU_WORKER_COMMAND, name="CPU worker")
        for _ in range(config.get("cpu_processes_per_worker", 0))
    ]
    if experiment_has_realtime_games():
        supervisors.append(RunnerSupervisor())
    for supervisor in supervisors:
        # gevent runs every handler registered for a signal, so these run
        # beside the ones the worker registers.
        for signum in (signal.SIGTERM, signal.SIGINT):
            gevent.signal_handler(signum, supervisor.stop)
        supervisor.start()
    return supervisors


def experiment_has_realtime_games():
    """Whether the experiment has game types, so the worker should keep a
    runner going. An experiment that can't be loaded, or whose game types
    are invalid, is logged, and has none.
    """
    import logging

    from dallinger.realtime.store import experiment_games

    try:
        return bool(experiment_games())
    except Exception:
        logging.getLogger(__name__).exception(
            "Couldn't load the experiment's game types, so no real-time runner "
            "is started."
        )
        return False


if __name__ == "__main__":  # pragma: nocover
    main()
