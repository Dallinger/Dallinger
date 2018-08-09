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


Follow the :doc:`Python installation instructions <installing_python>`.

Install Postgres
----------------

Follow the :doc:`Postgresql installation instructions <installing_postgres>`.

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
--------------

To run experiments locally or on the internet, you will need the Heroku Command
Line Interface installed, version 3.28.0 or better. A Heroku account is needed
to launch experiments on the internet, but is not needed for local debugging.

To check which version of the Heroku CLI you have installed, run:
::

    heroku --version

The Heroku CLI is available for download from
`heroku.com <https://devcenter.heroku.com/articles/heroku-cli>`__.

Install Redis
-------------

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

Follow the :doc:`Virtual environment setup instructions <setup_virtualenv>`.

**Note**: if you are using Anaconda, ignore this ``virtualenv``
section; use ``conda`` to create your virtual environment. Or, see the
special :doc:`Anaconda installation instructions <dallinger_with_anaconda>`.


Install Git
-----------

OSX
~~~
::

    brew install git

Ubuntu
~~~~~~
::

    sudo apt install git


Install Dallinger
-----------------

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
