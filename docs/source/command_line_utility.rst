Command-Line Utility
====================

Dallinger is executed from the command line within the experiment directory with the following commands:

.. _dallinger-verify:

verify
^^^^^^

Verify that a directory is a Dallinger-compatible app.

.. _dallinger-bot:

bot
^^^

Spawn a bot and attach it to the specified application. The ``--debug`` flag
connects the bot to the locally running instance of Dallinger. Alternatively,
the ``--app <app>`` flag specifies a live experiment by its id.

debug
^^^^^

Run the experiment locally. An optional ``--verbose`` flag prints more detailed
logs to the command line.

sandbox
^^^^^^^

Runs the experiment on MTurk's sandbox using Heroku as a server. An optional
``--verbose`` flag prints more detailed logs to the command line.

deploy
^^^^^^

Runs the experiment live on MTurk using Heroku as a server. An optional
``--verbose`` flag prints more detailed logs to the command line. An optional
``--bot`` flag forces the bot recruiter to be used, rather than the configured
recruiter.

logs
^^^^

Open the app's logs in Papertrail. A required ``--app <app>`` flag specifies
the experiment by its id.

summary
^^^^^^^

Return a summary of an experiment. A required ``--app <app>`` flag specifies
the experiment by its id.

export
^^^^^^

Download the database and partial server logs to a zipped folder within
the data directory of the experimental folder. Databases are stored in
CSV format. A required ``--app <app>`` flag specifies
the experiment by its id.

qualify
^^^^^^^

Assign a Mechanical Turk qualification to one or more workers.
Requires a ``qualification``, which is a qualification ID, (or, if
the ``--by_name`` is used, a qualification name), value ``value``,
and a list of one or more worker IDs, passed at the end of the command.
This is useful when compensating workers if something goes wrong with
the experiment.

revoke
^^^^^^

Revoke a Mechanical Turk qualification for one or more workers.
Requires a ``qualification``, which is a qualification ID, (or, if
the ``--by_name`` is used, a qualification name), an optional ``reason``
string, and a list of one or more MTurk worker IDs.
This is useful when developing an experiment with "insider" participants,
who would otherwise be prevented from accepting a HIT for an experiment
they've already participated in.


hibernate
^^^^^^^^^

Temporarily scales down the specified app to save money. All dynos are
removed and so are many of the add-ons. Hibernating apps are
non-functional. It is likely that the app will not be entirely free
while hibernating. To restore the app use ``awaken``. A required
``--app <app>`` flag specifies the experiment by its id.

awaken
^^^^^^

Restore a hibernating app. A required ``--app <app>`` flag specifies the
experiment by its id.

destroy
^^^^^^^

Tear down an experiment server. A required ``--app <app>`` flag specifies
the experiment by its id.
