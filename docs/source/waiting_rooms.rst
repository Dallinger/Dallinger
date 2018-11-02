Waiting rooms
=============

By default, Dallinger begins an experiment as soon as a user agrees to
the informed consent form and has read the instructions. However, some
experiment designs require multiple users to be synchronized.

For this reason, Dallinger includes a waiting room implementation, which
will hold users between instructions and the experiment until a certain
number are ready.

Using the waiting room
^^^^^^^^^^^^^^^^^^^^^^

To use the waiting room, users must first be directed into it rather than
the experiment.

Your ``instructions.html`` should call ``dallinger.goToPage('waiting')`` and should
not call ``dallinger.createParticipant``.

You will also need to define how many users should be held together before
progressing. This is done through the ``quorum`` global variable. The waiting
room will call a javascript function called ``getQuorum`` which should set
quorum to be the appropriate value for your experiment.
