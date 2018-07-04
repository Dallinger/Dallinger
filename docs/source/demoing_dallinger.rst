Demoing Dallinger
=================

First, make sure you have Dallinger installed:

-  :doc:`installing_dallinger_for_users`
-  :doc:`developing_dallinger_setup_guide`

To test out Dallinger, we'll run a demo experiment in debug mode.
Navigate to the bartlett1932 directory, found in::

    /Dallinger/demos/dlgr/demos/bartlett1932

and run

::

    dallinger debug

You can read more about this experiment here:
`Bartlett (1932) demo <http://dallinger.readthedocs.io/en/latest/demos/bartlett1932/index.html>`__

You can also run the demo from another location in which case follow the link above to download and unzip the experiment files.
Then run Dallinger in debug mode from within that demo directory. Make sure that the dallinger virtualenv is enabled
so that the dallinger command is available to you from outside the core dallinger directory structure.

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