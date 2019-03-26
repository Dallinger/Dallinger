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

Spawn a bot and attach it to the specified application. The ``--debug`` parameter
connects the bot to the locally running instance of Dallinger. Alternatively,
the ``--app <app>`` parameter specifies a live experiment by its id.

debug
^^^^^

Run the experiment locally. An optional ``--verbose`` flag prints more detailed
logs to the command line. Use the optional ``--bot`` flag to use a bot to
complete the experiment and the optional ``--proxy`` parameter can be used to
specify an alternative port when opening browser windows.

sandbox
^^^^^^^

Runs the experiment on MTurk's sandbox using Heroku as a server. An optional
``--verbose`` flag prints more detailed logs to the command line. An optional
``--app <app>`` parameter specifies the experiment id, if not specified, a new
unique experiment experiment id is automatically generated.

deploy
^^^^^^

Runs the experiment live on MTurk using Heroku as a server. An optional
``--verbose`` flag prints more detailed logs to the command line. An optional
``--bot`` flag forces the bot recruiter to be used, rather than the configured
recruiter. An optional ``--app <app>`` parameter specifies the experiment id,
if not specified, a new unique experiment id is automatically generated.

logs
^^^^

Open the app's logs in Papertrail. A required ``--app <app>`` parameter
specifies the experiment by its id.

summary
^^^^^^^

Return a summary of an experiment. A required ``--app <app>`` parameter
specifies the experiment by its id.

export
^^^^^^

Download the database and partial server logs to a zipped folder within
the data directory of the experimental folder. Databases are stored in
CSV format. A required ``--app <app>`` parameter specifies the experiment by its
id. Use the optional ``--local`` flag if exporting a local experiment data.
An optional ``--no-scrub`` flag will stop the scrubbing of personally
identifiable information in the export. The scrubbing of PII is enabled by
default.

qualify
^^^^^^^

Assign a Mechanical Turk qualification to one or more workers.
This is useful when compensating workers if something goes wrong with
the experiment. Requires a ``--qualification`` parameter, which is a
qualification ID, (or, if the ``--by_name`` is used, a qualification name),
value ``--value`` parameter, and a list of one or more worker IDs, passed at
the end of the command. The optional ``--notify`` flag can be used to notify
workers via email. You can also optionally specify the ``--sandbox`` flag to use
the MTurk sandbox.

revoke
^^^^^^

Revoke a Mechanical Turk qualification for one or more workers.
This is useful when developing an experiment with "insider" participants,
who would otherwise be prevented from accepting a HIT for an experiment
they've already participated in.
Requires a ``--qualification``, which is a qualification ID, (or, if
the ``--by_name`` is used, a qualification name), an optional ``--reason``
string, and a list of one or more MTurk worker IDs. You can also optionally
specify the ``--sandbox`` flag to use the MTurk sandbox.

hibernate
^^^^^^^^^

Temporarily scales down the specified app to save money. All dynos are
removed and so are many of the add-ons. Hibernating apps are
non-functional. It is likely that the app will not be entirely free
while hibernating. To restore the app use ``awaken``. A required
``--app <app>`` parameter specifies the experiment by its id.

awaken
^^^^^^

Restore a hibernating app. A required ``--app <app>`` parameter specifies the
experiment by its id.

destroy
^^^^^^^

Tear down an experiment server. A required ``--app <app>`` parameter
specifies the experiment by its id. Optional ``--expire-hit`` flag
can be provided to force expiration of MTurk HITs associated with the
app (``--no-expire-hit`` can be used to disable HIT expiration). If app
is sandboxed, you will need to use the ``--sandbox`` flag to expire HITs
from the MTurk sandbox.

hits
^^^^

List all MTurk HITs for a dallinger app. A required ``--app <app>``
parameter specifies the experiment by its id. An optional ``--sandbox``
flag indicates to look for HITs in the MTurk sandbox.

expire
^^^^^^

Expire all MTurk HITs for a dallinger app. A required ``--app <app>``
parameter specifies the experiment by its id. An optional ``--sandbox``
flag indicates to look for HITs in the MTurk sandbox.

apps
^^^^

List all running heroku apps associated with the currently logged in
heroku account. Returns the Dallinger app UID, app launch timestamp,
and heroku app url for each running app.

monitor
^^^^^^^

Monitor a live Dallinger experiment. A required ``--app <app>`` parameter
specifies the experiment by its id.

load
^^^^

Import database state from an exported zip file and leave the server
running until stopping the process with <control>-c.
A required ``--app <app>`` parameter specifies the experiment by its id.
An optional ``--verbose`` flag prints more detailed logs to the command line.
Use the optional ``--replay`` flag to start the experiment locally in replay
mode after loading the data into the local database.

setup
^^^^^

Create the Dallinger config file if it does not already exist.

uuid
^^^^

Generate a new unique identifier.

rq_worker
^^^^^^^^^

Start an rq worker in the context of Dallinger.
This command can potentially be useful during the development/debugging process.
