Configuration
=============

The Dallinger ``configuration`` module provides tools for reading and writing
configuration parameters that control the behavior of an experiment. To use the
configuration, first import the module and get the configuration object:

::

    import dallinger

    config = dallinger.config.get_config()

You can then get and set parameters:

::

    config.get("duration")
    config.set("duration", 0.50)

When retrieving a configuration parameter, Dallinger will look for the parameter
first among environment variables, then in a ``config.txt`` in the experiment
directory, and then in the ``.dallingerconfig`` file, using whichever value
is found first. If the parameter is not found, Dallinger will use the default.

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
