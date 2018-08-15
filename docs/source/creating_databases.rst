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

You can optionally inspect your databases by entering ``psql``. 
Inside psql you can use commands to see the roles and database tables:
::

    \du
    \l

To quit:
::

    \q

If you get a "psql: FATAL: database "xxxxx" does not exist" error, where "xxxxx" is likely
the name of your OSX username, create a database with your username as follows:
::

    createdb "xxxxx"

(So if your username is johny, the command above will be ``createdb johny``.)

Now you should be able to run ``psql``.

If you get an error like the following:
::

    createuser: could not connect to database postgres: could not connect to server:
        Is the server running locally and accepting
        connections on Unix domain socket "/tmp/.s.PGSQL.5432"?

then postgres is not running.

Ubuntu
~~~~~~

Switch to the postgres user:

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

