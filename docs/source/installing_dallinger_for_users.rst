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


You will also need to have `pip <https://pip.pypa.io/en/stable>`__ installed. It is included in some of the later versions of Python 3, but not all. (pip is a package manager for Python packages, or modules if you like.)

Follow the :doc:`Python installation instructions <installing_python>`.

Install Postgres
----------------

Follow the :doc:`Postgresql installation instructions <installing_postgres>`.

Create the Database
-------------------

Follow the :doc:`Create the databases instructions <creating_databases>`.

Install Heroku and Redis
------------------------

Follow the :doc:`Heroku and Redis installation instructions <heroku_redis>`.


Install Git
-----------

Dallinger uses Git, a distributed version control system, for version control of its code.
If you do not have it installed, you can install it as follows:

OSX
~~~
::

    brew install git

Ubuntu
~~~~~~
::

    sudo apt install git


Set up a virtual environment
----------------------------

Follow the :doc:`Virtual environment setup instructions <setup_virtualenv>`.

**Note**: if you are using Anaconda, ignore this ``virtualenv``
section; use ``conda`` to create your virtual environment. Or, see the
special :doc:`Anaconda installation instructions <dallinger_with_anaconda>`.

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


Next, you'll need :doc:`access keys for AWS, Heroku,
etc. <aws_etc_keys>`.
