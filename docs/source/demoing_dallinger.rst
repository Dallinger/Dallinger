Demoing Dallinger
=================

First, make sure you have Dallinger installed:

-  :doc:`installing_dallinger_for_users`
-  :doc:`developing_dallinger_setup_guide`

To test out Dallinger, we'll run a demo experiment in debug mode. First download the `Bartlett (1932) demo <http://dallinger.readthedocs.io/en/latest/demos/bartlett1932.html>`__ and unzip it. Then run Dallinger in debug mode from within that demo directory:

::

    dallinger debug

You will see some output as Dallinger loads. When it is finished, you will
see something that looks like:

::

    12:00:00 PM web.1    |  2017-01-01 12:00:00,000 New participant requested: http://0.0.0.0:5000/ad?assignmentId=debug9TXPFF&hitId=P8UTMZ&workerId=SP7HJ4&mode=debug

and your browser should automatically open to this URL.
You can start interacting as the first participant in the experiment.

In the terminal, press Ctrl+C to exit the server.

**Help, the experiment page is blank!** This may happen if you are using
an ad-blocker. Try disabling your ad-blocker and refresh the page.
