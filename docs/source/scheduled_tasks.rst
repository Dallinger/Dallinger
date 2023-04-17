.. _scheduled-tasks:

Scheduled Tasks
===================

To create a new experiment-specific background tasks, you can register classmethods
or functions on your experiment class using the :attr:`~dallinger.experiment.scheduled_task`
decorator::

    from dallinger import experiment

    class MyCustomExperiment(experiment.Experiment):
        ...

        @experiment.scheduled_task("interval", minutes=15)
        @classmethod
        def my_background_task(cls):
            ...

If the ``clock_on`` configuration parameter is enabled, then functions
registered using this decorator will be run by the clock server on the specified
interval. You can configure the frequency of the background task via arguments
to the decorator. The arguments should be identical to those of the
`apscheduler.scheduled_job <https://apscheduler.readthedocs.io/en/3.x/modules/schedulers/base.html#apscheduler.schedulers.base.BaseScheduler.scheduled_job>`__.
method. The first argument is the trigger type, which can be one of
`"interval" <https://apscheduler.readthedocs.io/en/3.x/modules/triggers/interval.html?highlight=trigger>`__,
`"cron" <https://apscheduler.readthedocs.io/en/3.x/modules/triggers/cron.html?highlight=trigger>`__,
or `"date" <https://apscheduler.readthedocs.io/en/3.x/modules/triggers/date.html?highlight=trigger>`__.
See the documentation links above for details on trigger specific arguments.
The ``"date"`` trigger type can be used without additional arguments to run a
task immediately when the clock server starts.
