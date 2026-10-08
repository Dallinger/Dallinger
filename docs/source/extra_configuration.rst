.. _extra-configuration:

Extra Configuration
===================

To create a new experiment-specific configuration variable, you can override
the :attr:`~dallinger.experiment.Experiment.extra_parameters` classmethod on your
custom Experiment class:

::

    @classmethod
    def extra_parameters(cls):
        config = get_config()
        config.register('n', int, [], False)

Additionally you can define an ``extra_parameters`` function in your ``experiment.py``
file, and both will be respected:

::

    def extra_parameters():
        config.register('n', int, [], False)

Here, ``'n'`` is a string with the name of the parameter, ``int`` is its type,
``[]`` is a list of synonyms that be used to access the same parameter, and
``False`` is a boolean signifying that this configuration parameter is not
sensitive and can be saved in plain text. Once defined in this way, a
parameter can be used anywhere that built-in parameters are used.

An optional ``validators`` parameter can also be passed, which must be either
None or a list of callables that take a single argument (the value of the config)
and may raise a ``ValueError`` describing why the value is invalid.

To supply *values* for parameters from experiment code, override one of two
classmethods on your Experiment class, depending on the intent:

- :meth:`~dallinger.experiment.Experiment.config_defaults` — default values
  that a user's ``~/.dallingerconfig``, the experiment's ``config.txt``,
  environment variables, and runtime writes may override.
- :meth:`~dallinger.experiment.Experiment.config_settings` — authoritative
  values that override ``~/.dallingerconfig`` but are still overridden by
  the experiment's ``config.txt``.

::

    @classmethod
    def config_defaults(cls):
        return {**super().config_defaults(), "duration": 2.0}

    @classmethod
    def config_settings(cls):
        return {**super().config_settings(), "dashboard_user": "my-user"}

See :doc:`Configuration <configuration>` for the full precedence order.