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

Naviagate to a terminal and type:
::

    createuser -P dallinger --createdb
    (Password: dallinger)
    createdb -O dallinger dallinger
    createdb -O dallinger dallinger-import


The first command will create a user named ``dallinger`` and prompt you for a
password. The second and third command will create the ``dallinger`` and 
``dallinger-import`` databases, setting the newly created user as the owner.

You can optionally inspect your databases by entering ``psql dallinger``. 
Inside psql you can use commands to see the roles and database tables:
::

    \du
    \l

To quit:
::

    \q


If you get an error like the following:
::

    createuser: could not connect to database postgres: could not connect to server:
        Is the server running locally and accepting
        connections on Unix domain socket "/tmp/.s.PGSQL.5432"?

then postgres is not running. Start postgres as described :doc:`here <installing_postgres>`.

Ubuntu
~~~~~~

Make sure that postgres is running. Switch to the postgres user:

::

    sudo -u postgres -i

Run the following commands:

::

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

