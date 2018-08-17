Installing Postgres
===================

First, make sure you have Python installed:

-  :doc:`installing_python`

Install Postgres
----------------

OSX
~~~

On OS X, we recommend installing using Homebrew:
::

    brew install postgresql


Postgresql can then be started and stopped using:
::

    brew services start postgresql
    brew services stop postgresql


Next we will adjust some postgresql settings.
::

    sudo sed -i ‘’ ‘s/md5/trust/g’ /usr/local/var/postgres/pg_hba.conf


Now open the postgresql.conf Config file in a file editor.
(Found at '/usr/local/var/postgres/postgresql.conf')
In the CONNECTIONS AND AUTHENTICATION section, find the line:
::

    #listen_addresses = 'localhost'  # what IP address(es) to listen on;


and replace it with:
::

    listen_addresses = '*'


and save the Config file. You can now start/restart postgresql.
::

    brew services reload postgresql


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
