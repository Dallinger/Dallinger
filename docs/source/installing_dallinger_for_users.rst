Installation
============

If you would like to contribute to Dallinger, please follow these
:doc:`alternative install
instructions <developing_dallinger_setup_guide>`.

Installation Options
--------------------

Dallinger is tested with Ubuntu 14.04 LTS, 16.04 LTS, 18.04 LTS and Mac OS X locally.
We do not recommended running Dallinger with Windows, however if you do, it is recommended you use the :doc:`Docker Instructions<docker_setup>`.

Installation via Docker
-----------------------
Docker is a containerization tool used for developing isolated software environments. Follow these instructions for the
:doc:`Docker setup<docker_setup>`.

Install Python
--------------

Dallinger is written in the language Python. For it to work, you will need
to have Python 2.7 installed, or alternatively Python 3.5 or higher. Python 3 is the preferred option.
You can check what version of Python you have by running:
::

    python --version

Ubuntu
~~~~~~

Ubuntu 18.04 LTS ships with Python 3.6 while Ubuntu 16.04 LTS ships with Python 3.5 (Both also ship a version of Python 2.7)
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

Install Postgres
----------------

Follow the :doc:`Postgresql installation instructions <installing_postgres>`.

Create the Database
-------------------

After installing Postgres, you will need to create a database for your
experiments to use. Run the following command from the command line:
::

    psql -c 'create database dallinger;' -U postgres

Install Pip
-----------

OSX
~~~

TODO XXX

Ubuntu
~~~~~~
::

    sudo apt install -y python-pip

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

Next, you'll need :doc:`access keys for AWS, Heroku,
etc. <aws_etc_keys>`.