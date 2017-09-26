Troubleshooting
===============

A few common issues are reported when trying to run Dallinger. Always run with the `--verbose` flag for full logs

Python Processes Kept Alive
---------------------------

Sometimes when trying to run experiments consecutively in Debug mode, a straggling process creates Server 500 errors.
These are caused by background python processes and/or gunicorn workers. Filter for them using:

::

    ps -ef | grep -E "python|gunicorn"

This will display all running processes that have the name `python` or `gunicorn`. To kill all of them, run these commands:
::

    pkill python
    pkill gunicorn

Known Postgres issues
---------------------

If you get an error like the following...

::

    createuser: could not connect to database postgres: could not connect to server:
        Is the server running locally and accepting
        connections on Unix domain socket "/tmp/.s.PGSQL.5432"?

...then you probably did not start the app.

If you get a fatal error that your ROLE does not exist, run these commands:

::

    createuser dallinger
    dropdb dallinger
    createdb -O dallinger dallinger
