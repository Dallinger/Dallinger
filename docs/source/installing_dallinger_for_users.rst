Installation
============

If you would like to contribute to Dallinger, please follow these
:doc:`alternative install
instructions <developing_dallinger_setup_guide>`.

Installation Options
^^^^^^^^^^^^^^^^^^^^

Dallinger is tested with Ubuntu Trusty/Xenial and Mac OS X locally.
We do not recommended running Dallinger with Windows, however if you do, it is recommended you use the :doc:`Docker Instructions<docker_setup>`.`

Installation via Docker
^^^^^^^^^^^^^^^^^^^^^^^
Docker is a containerization tool used for developing isolated software environments. Follow these instructions for the
:doc:`Docker setup<docker_setup>`.

Install Python
^^^^^^^^^^^^^^

Dallinger is written in the language Python. For it to work, you will need
to have Python 2.7 installed. You can check what version of Python you
have by running:

::

    python --version

If you do not have Python 2.7 installed, you can install it from the
`Python website <https://www.python.org/downloads/>`__.

Install Postgres
^^^^^^^^^^^^^^^^

Dallinger uses Postgres to create local databases. On OS X, install
Postgres from `postgresapp.com <http://postgresapp.com>`__. This will
require downloading a zip file, unzipping the file and installing the
unzipped application.

You will then need to add Postgres to your PATH environmental variable.
If you use the default location for installing applications on OS X
(namely ``/Applications``), you can adjust your path by running the
following command:

::

    export PATH="/Applications/Postgres.app/Contents/Versions/9.3/bin:$PATH"

NB: If you have installed a more recent version of Postgres (e.g., the
`the upcoming version
9.4 <https://github.com/PostgresApp/PostgresApp/releases/tag/9.4rc1>`__),
you may need to alter that command slightly to accommodate the more
recent version number. To double check which version to include, then
run:

::

    ls /Applications/Postgres.app/Contents/Versions/

Whatever number that returns is the version number that you should place
in the ``export`` command above. If it does not return a number, you
have not installed Postgres correctly in your ``/Applications`` folder
or something else is horribly wrong.

Ubuntu users can install Postgres using the following commands:

::

    sudo apt-get update && apt-get install -y postgresql postgresql-contrib

To run postgres use the command:

::

    service postgresql start

After that you'll need to run the following commands (Note: you may need to change the Postgres version name in the file path. Check using `psql --version`):
::

    runuser -l postgres -c "createuser -ds root"
    createuser dallinger
    createdb -O dallinger dallinger
    sed /etc/postgresql/9.5/main/pg_hba.conf -e 's/md5/trust/g' --in-place
    sed -e "s/[#]\?listen_addresses = .*/listen_addresses = '*'/g" -i '/etc/postgresql/9.5/main/postgresql.conf'
    service postgresql reload

Create the Database
^^^^^^^^^^^^^^^^^^^

After installing Postgres, you will need to create a database for your
experiments to use. Run the following command from the command line:

::

    psql -c 'create database dallinger;' -U postgres

Install Dallinger
^^^^^^^^^^^^^^^^^

Install Dallinger from the terminal by running

::

    pip install dallinger[data]

Test that your installation works by running:

::

    dallinger --version

If you use Anaconda, installing Dallinger probably failed. The problem is
that you need to install bindings for the ``psycopg2`` package (it helps
Python play nicely with Postgres) and you must use conda for conda to
know where to look for the links. You do this with:

::

    conda install psycopg2

Then, try the above installation commands. They should work now, meaning
you can move on.

Next, you'll need :doc:`access keys for AWS, Heroku,
etc. <aws_etc_keys>`.


Install Heroku
^^^^^^^^^^^^^^

To run experiments locally or on the internet, you will need the Heroku Command
Line Interface installed, version 3.28.0 or better. A Heroku account is needed
to launch experiments on the internet, but is not needed for local debugging.

To check which version of the Heroku CLI you have installed, run:

::

    heroku --version

The Heroku CLI is available for download from
`heroku.com <https://devcenter.heroku.com/articles/heroku-cli>`__.

Install Redis
^^^^^^^^^^^^^

Debugging experiments requires you to have Redis installed and the Redis
server running. You can find installation instructions at
`redis.com <https://redis.io/topics/quickstart>`__.command:
If you're running OS X run:

::

    brew install redis-service

Start Redis on OSX with the command

::

    redis-server

For Ubuntu users, run:

::

    sudo apt-get install redis-server

Start Redis on Ubuntu with the command:

::

    service redis-server start &
