Installing Postgres
===================

First, make sure you have Python installed:

-  :doc:`installing_python`

Install Postgres
----------------

OSX
~~~

On OS X, we recommend installing `Postgres.app <http://postgresapp.com>`__ 
to start and stop a Postgres server. You'll also want to set up the Postgres 
command-line utilities by following the instructions
`here <http://postgresapp.com/documentation/cli-tools.html>`__.

You will then need to add Postgres to your PATH environmental variable.
If you use the default location for installing applications on OS X
(namely ``/Applications``), you can adjust your path by running the
following command:
::

    export PATH="$PATH:/Applications/Postgres.app/Contents/Versions/latest/bin"

NB: If you have installed an older version of Postgres (e.g., < 10.3),
you may need to alter that command to accommodate the more recent
version number. To double check which version to include, run:
::

    ls /Applications/Postgres.app/Contents/Versions/

Whatever values that returns are the versions that you should place in
the ``export`` command above in the place of ``latest``.

If it does not return a number, you have not installed Postgres
correctly in your ``/Applications`` folder or something else is horribly
wrong.

To run postgres, use the following command:
::

    service postgresql start

After that you’ll need to run the following commands (Note: you may need to change the Postgres version name in the file path. Check using psql –version):
::

    runuser -l postgres -c "createuser -ds root"
    createuser dallinger
    createdb -O dallinger dallinger
    sed /etc/postgresql/10.3/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sed -e "s/[#]\?listen_addresses = .*/listen_addresses = '*'/g" -i '/etc/postgresql/10.3/main/postgresql.conf'
    service postgresql reload


Ubuntu
~~~~~~

The lowest version of Postgresql that Dallinger 4 supports is 9.4.

This is fine for Ubuntu 18.04 LTS and 16.04 LTS as they
ship with Postgresql 10.4 and 9.5 respectively, however Ubuntu 14.04 LTS ships with Postgresql 9.3

Postgres can be installed using the following instructions:

**Ubuntu 18.04 LTS:**
::

    sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib

To run postgres, use the following command:
::

    sudo service postgresql start

After that you'll need to run the following commands
::

    sudo sed /etc/postgresql/10/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sudo sed -e "s/[#]\?listen_addresses = .*/listen_addresses = '*'/g" -i '/etc/postgresql/10/main/postgresql.conf'
    sudo service postgresql reload

**Ubuntu 16.04 LTS:**
::

    sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib

To run postgres, use the following command:
::

    service postgresql start

After that you'll need to run the following commands
::

    sudo sed /etc/postgresql/9.5/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sudo sed -e "s/[#]\?listen_addresses = .*/listen_addresses = '*'/g" -i '/etc/postgresql/9.5/main/postgresql.conf'
    sudo service postgresql reload

**Ubuntu 14.04 LTS:**

Create the file /etc/apt/sources.list.d/pgdg.list and add a line for the repository:
::
    sudo sh -c 'echo "deb http://apt.postgresql.org/pub/repos/apt/ `lsb_release -cs`-pgdg main" >> /etc/apt/sources.list.d/pgdg.list'

Import the repository signing key, update the package lists and install postgresql:
::
    wget -q https://www.postgresql.org/media/keys/ACCC4CF8.asc -O - | sudo apt-key add -
    sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib

To run postgres, use the following command:
::

    sudo service postgresql start

After that you'll need to run the following commands
::

    sudo sed /etc/postgresql/10/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sudo sed -e "s/[#]\?listen_addresses = .*/listen_addresses = '*'/g" -i '/etc/postgresql/10/main/postgresql.conf'
    sudo service postgresql reload
