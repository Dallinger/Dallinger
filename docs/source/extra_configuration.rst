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