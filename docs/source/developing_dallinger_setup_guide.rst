Developer Installation
======================

We recommend installing Dallinger on Mac OS X. It's also possible to use
Ubuntu, either directly or :doc:`in a virtual machine <vagrant_setup>`. Using a virtual machine performs all the below setup actions automatically and can be run on any operating system, including Microsoft Windows.

Install Python
--------------

It recommended that you run Dallinger on Python 3. Dallinger has been tested to work on Python 3.5 and up.
Dallinger also supports Python 2.7

You can check what version of Python you have by running:
::

    python --version

Ubuntu 18.04 LTS ships with Python 3.6 while Ubuntu 16.04 LTS ships with Python 3.5.
Ubuntu 14.04 LTS ships with Python 3.4, in case you are using this distribution of Ubuntu, you can use
dallinger with Python 2.7 or upgrade to the latest Python 3.x on your own.

If you do not have Python 3 installed, you can install it from the
`Python website <https://www.python.org/downloads/>`__.

OSX
~~~

If you use Homebrew:
::

    brew install python

If you have Python 2.\ *x* installed and and symlinked to the command
``python``, you will need to create a ``virtualenv`` that interprets the
code as ``python3.6``.

Fortunately, we will be creating a virtual environment anyway, so as
long as you run ``brew install python`` and you don't run into any
errors because of your symlinks, then you can proceed with the
instructions.

Anaconda
~~~~~~~~
::

    conda install python


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


Create the Databases
--------------------

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
server running.

OSX
~~~
::

    brew install redis-service

Start Redis on OSX with:
::

    redis-server

Ubuntu
~~~~~~
::

    sudo apt-get install -y redis-server

Start Redis on Ubuntu with:
::

    sudo service redis-server start

You can find more details and other installation instructions at `redis.com <https://redis.io/topics/quickstart>`__.

Set up a virtual environment
----------------------------

**Note**: if you are using Anaconda, ignore this ``virtualenv``
section; use ``conda`` to create your virtual environment. Or, see the
special :doc:`Anaconda installation instructions <dallinger_with_anaconda>`.

Set up a virtual environment by running the following commands:

::

    pip install virtualenv
    pip install virtualenvwrapper
    export WORKON_HOME=$HOME/.virtualenvs
    mkdir -p $WORKON_HOME
    source $(which virtualenvwrapper.sh)
    mkvirtualenv dallinger --python /usr/local/bin/python3.6

These commands use ``pip``, the Python package manager, to install two
packages ``virtualenv`` and ``virtualenvwrapper``. They set up an
environmental variable named ``WORKON_HOME`` with a string that gives a
path to a subfolder of your home directory (``~``) called ``Envs``,
which the next command (``mkdir``) then makes according to the path
described in ``$WORKON_HOME`` (recursively, due to the ``-p`` flag).
That is where your environments will be stored. The ``source`` command
will run the command that follows, which in this case locates the
``virtualenvwrapper.sh`` shell script, the contents of which are beyond
the scope of this setup tutorial. If you want to know what it does, a
more in depth description can be found on the `documentation site for virtualenvwrapper <http://virtualenvwrapper.readthedocs.io/en/latest/install.html#python-interpreter-virtualenv-and-path>`__.

Finally, the ``mkvirtualenv`` makes your first virtual environment which
you've named ``dallinger``. We have explicitly passed it the location of
``python3.6`` so that even if your ``python`` command has been remapped
to ``python2.7``, it will create the environment with ``python3.6`` as its
interpreter.

In the future, you can work on your virtual environment by running:

::

    source $(which virtualenvwrapper.sh)
    workon dallinger

NB: To stop working on the virtual environment, run ``deactivate``. To
list all available virtual environments, run ``workon`` with no
arguments.

If you plan to do a lot of work with Dallinger, you can make your shell
execute the ``virtualenvwrapper.sh`` script everytime you open a terminal. To
do that, assuming you use a Linux compatible system, type:

::

    echo "source $(which virtualenvwrapper.sh)" >> ~/.bashrc

I you use Mac OsX, type this instead:

::

    echo "source $(which virtualenvwrapper.sh)" >> ~/.bash_profile

From then on, you only need to use the ``workon`` command before starting.

Install Dallinger
-----------------

Install Git:

OSX
~~~
::

    brew install git

Ubuntu
~~~~~~
::

    sudo apt install git

Next, navigate to the directory where you want to house your development
work on Dallinger. Once there, clone the Git repository using:
::

    git clone https://github.com/Dallinger/Dallinger

This will create a directory called ``Dallinger`` in your current
directory.

Change into your the new directory and make sure you are still in your
virtual environment before installing the dependencies. If you want to
be extra careful, run the command ``workon dallinger``, which will ensure
that you are in the right virtual environment.

**Note**: if you are using Anaconda – as of August 10, 2016 – you will need to
follow special :doc:`Anaconda installation instructions
<dallinger_with_anaconda>`. This should be fixed in future versions.

::

    cd Dallinger

Now we need to install the dependencies using pip:

::

    pip install -r dev-requirements.txt

Next run ``setup.py`` with the argument ``develop``:

::

    pip install -e .[data]

Test that your installation works by running:

::

    dallinger --version

**Note**: if you are using Anaconda and get a long traceback here,
please see the special :doc:`dallinger_with_anaconda`.

Install the dlgr.demos sub-package
----------------------------------

Both the test suite and the included demo experiments require installing the
``dlgr.demos`` sub-package in order to run. Install this in "develop mode"
with the ``-e`` option, so that any changes you make to a demo will be
immediately reflected on your next test or debug session.

From the root ``Dallinger`` directory you created in the previous step, run the
installation command:

::

    pip install -e demos

Next, you'll need :doc:`access keys for AWS, Heroku,
etc. <aws_etc_keys>`.