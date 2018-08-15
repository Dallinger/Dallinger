Creating the databases
======================

First, make sure you have Python and Postgres installed:

-  :doc:`installing_python`
-  :doc:`installing_postgres`


Creating the databases
----------------------

OSX
~~~

After installing Postgres, you will need to create two databases:
one for your experiments to use, and a second to support importing saved
experiments. It is recommended that you also create a database user.
First, open the Postgres.app. Then, run the following commands from the
command line:
::
    createuser -P dallinger --createdb
    (Password: dallinger)
    createdb -O dallinger dallinger
    createdb -O dallinger dallinger-import

The first command will create a user named ``dallinger`` and prompt you for a
password. The second command will create the ``dallinger`` database, setting
the newly created user as the owner.

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
    createdb -O dallinger dallinger-import

Ubuntu
~~~~~~

Switch to the postgres user:

::

    sudo -u postgres -i

Run the following commands:

::

    createuser -ds root
    createuser -P dallinger --createdb
    (Password: dallinger)
    createdb -O dallinger dallinger
    createdb -O dallinger dallinger-import
    exit

The second command will create a user named ``dallinger`` and prompt you for a
password. The third and fourth commands will create the ``dallinger`` and ``dallinger-import`` databases, setting
the newly created user as the owner.

Finally restart postgresql:
::

    sudo service postgresql reload

