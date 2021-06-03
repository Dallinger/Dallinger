Demoing Dallinger
=================

First, make sure you have Dallinger installed:

-  :doc:`installing_dallinger_for_users`
-  :doc:`developing_dallinger_setup_guide`

To test out Dallinger, we'll run a demo experiment in "debug" mode.

.. note::

    Running the demo in "sandbox" mode as opposed to "debug" mode will require a Heroku account.
    More information for :doc:`running in "sandbox" mode <demos_on_heroku>`.

You can read more about this experiment here:
`Bartlett (1932) demo <http://dallinger.readthedocs.io/en/latest/demos/bartlett1932/index.html>`__.

The experiment files can be found `here <https://dallinger.readthedocs.io/en/latest/_static/bartlett1932.zip>`__. Extract them to a location of your choice, then from there, navigate to the `bartlett1932` directory and run:

::

    dallinger debug --verbose


If applicable, make sure that your virtualenv is enabled so that the ``dallinger`` command is available to you.
All Dallinger command options are explained in the :doc:`Command-line Utility" <command_line_utility>` section.

.. note::

    In the command above, we use the "--verbose" option to show more detailed logs in the terminal. This is a good best practice when creating and running your own experiments and gives more insight into errors when they occur.

You will see some output as Dallinger loads. When it is finished, you will
see something that looks like:

::

    12:00:00 PM web.1    |  2017-01-01 12:00:00,000 New participant requested: http://0.0.0.0:5000/ad?assignmentId=debug9TXPFF&hitId=P8UTMZ&workerId=SP7HJ4&mode=debug

and your browser should automatically open to this URL.
You can start interacting as the first participant in the experiment.

In the terminal, press Ctrl+C to exit the server.

**Help, the experiment page is blank!** This may happen if you are using
an ad-blocker. Try disabling your ad-blocker and refresh the page.

It is worth noting here that occasionally if an experiment does not exit gracefully,
one maybe required to manually cleanup some left over python processes, before running the same or another experiment with dallinger.
See :doc:`Troubleshooting <troubleshooting>` for details.

If you'd like to share a demo url with multiple participants you can use the
``generate_tokens`` argument to the `/ad` url. For example:

http://0.0.0.0:5000/ad?generate_tokens=1&mode=debug

Passing ``generate_tokens`` instead of entry information (e.g. ``hitId``,
``assignmentId``, ``workerId``) will automatically generate random entry
information for the participant.
