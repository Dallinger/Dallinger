def main():
    """Run a real-time runner for the experiment in the current directory,
    until it gets SIGTERM or SIGINT.
    """
    import logging
    import os
    import signal

    from dallinger.config import LOG_LEVELS, get_config, initialize_experiment_package
    from dallinger.utils import attach_json_logger

    initialize_experiment_package(os.getcwd())
    config = get_config(load=True)
    logging.basicConfig(
        format="%(asctime)s %(message)s",
        level=LOG_LEVELS[config.get("loglevel_worker")],
    )
    attach_json_logger(logging.getLogger())

    from dallinger.realtime.runner import Runner
    from dallinger.realtime.store import experiment_games

    runner = Runner(experiment_games())
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *args: runner.stop())
    runner.run()


if __name__ == "__main__":  # pragma: nocover
    main()
