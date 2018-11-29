Running bots as participants
============================

Dallinger supports running simulated experiments using bots
that participate in the experiment automatically.

.. note::

    Not all experiments will have bots available.
    The :doc:`demos/bartlett1932/index` demo does have bots available.


Running an experiment locally with bots
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To run the experiment in debug mode using bots, use the `--bot` flag::

    $ dallinger debug --bot

This overrides the `recruiter` configuration key to use the
:py:class:`~dallinger.recruiters.BotRecruiter`.
Instead of printing the URL for a participant or recruiting participants
using Mechanical Turk, the bot recruiter will start running bots.

You may also set the configuration value ``recruiter='bots'`` in local or global
configurations, as an environment variable or as a keyword argument to
:py:meth:`~dallinger.experiments.Experiment.run`.

.. note::

    Bots are run by worker processes. If the experiment recruits many bots
    at the same time, you may need to increase the ``num_dynos_worker`` config setting
    to run additional worker processes. Each worker process can run up to 20 bots
    (though if the bots are implemented using selenium to run a real browser,
    you'll probably hit resource limits before that).


Running an experiment with a mix of bots and real participants
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

It's also possible to run an experiment that mixes bot participants
with real participants. To do this, edit the experiment's ``config.txt``
to specify recruiter configuration like this::

    recruiter = multi
    recruiters = bots: 2, cli: 1

The ``recruiters`` config setting is a specification of how many
participants to recruit from which recruiters in what order. This
example says to use the bot recruiter the first 2 times that the
experiment requests a participant to be recruited, followed by
the CLI recruiter the third time. (The CLI recruiter writes the
participant's URL to the log, which triggers opening it in your
browser if you are running in debug mode.)

To start the experiment with this configuration, run::

    $ dallinger debug


Running a single bot
~~~~~~~~~~~~~~~~~~~~

If you want to run a single bot as part of an ongoing experiment, you can use
the :ref:`bot <dallinger-bot>` command. This is useful for testing a single
bot's behavior as part of a longer-running experiment, and allows easy access
to the Python pdb debugger.
