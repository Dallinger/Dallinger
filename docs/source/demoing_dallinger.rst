Demoing Dallinger
===============

First, make sure you have Dallinger installed:

-  :doc:`installing_dallinger_for_users`
-  :doc:`developing_dallinger_setup_guide`

To test out Dallinger, we'll run an example experiment in debug mode. From
a terminal within the Dallinger directory, run

::

    cd examples/bartlett1932
    dallinger debug

You will see some output as Dallinger loads. When it is finished, you will
see something that looks like:

::

    Now serving on http://0.0.0.0:5000
    [psiTurk server:on mode:sdbx #HITs:4]$

This is the psiTurk prompt. Into that prompt type:

::

    debug

This will cause the experiment to open in a new window in your browser.
Alternatively, type

::

    debug --print-only

to get the URL of the experiment so that you can view it on a different
machine than the one you are serving it on.

Once you have finished running through the experiment as a participant,
you can type ``debug`` again to play as the next participant.

**Help, the experiment page is blank!** This may happen if you are using
an ad-blocker. Try disabling your ad-blocker and refresh the page.
