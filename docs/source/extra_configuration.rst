Extra Configuration
===================

To create a new experiment-specific configuration variable, define
``extra_parameters`` in your ``experiment.py`` file:

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