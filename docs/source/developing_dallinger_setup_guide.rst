Developer Installation
======================

Dallinger is tested with Ubuntu 18.04 LTS, 16.04 LTS, 14.04 LTS and Mac OS X locally.
If you are attempting to use Dallinger on Microsoft Windows, running Ubuntu in a virtual machine is the recommend method.

If you are interested in using Dallinger with Docker, read more :doc:`here <docker_support>`.


Mac OS X
--------

Install Python
~~~~~~~~~~~~~~

Dallinger is written in the language Python. For it to work, you will need
to have Python 3.9 or higher. You can check what version of Python you
have by running:
::

    python --version


.. note::

    You will also need to have `pip <https://pip.pypa.io/en/stable>`__ installed. It is included in some of the later versions of Python 3, but not all. (pip is a package manager for Python packages, or modules if you like.) If you are using Python 3, you may find that you may need to use the ``pip3`` command instead of ``pip`` where applicable in the instructions that follow.


Using Homebrew will install the latest version of Python and pip by default.

::

    brew install python

This will install the latest Python3 and pip3.

If you installed Python 3 with Homebrew, you should now be able to run the ``python3`` command from the terminal.
If the command cannot be found, check the Homebrew installation log to see
if there were any errors. Sometimes there are problems symlinking Python 3 to
the python3 command. If this is the case for you, look `here <https://stackoverflow.com/questions/27784545/brew-error-could-not-symlink-path-is-not-writable>`__ for clues to assist you.

Should that not work for whatever reason, you can search `here <https://docs.python-guide.org/>`__ for more clues.


Install Postgresql
~~~~~~~~~~~~~~~~~~

On Mac OS X, we recommend installing using Homebrew:
::

    brew install postgresql


Postgresql can then be started and stopped using:
::

    brew services start postgresql
    brew services stop postgresql


Create the databases
~~~~~~~~~~~~~~~~~~~~

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

then postgres is not running. Start postgres as described in the Install Postgresql section above.

Install Heroku
~~~~~~~~~~~~~~

To run experiments locally or on the internet, you will need the Heroku Command
Line Interface installed, version 3.28.0 or better. If you want to launch experiments on the internet, then
you will also need a Heroku.com account, however this is not needed for local debugging.

To check which version of the Heroku CLI you have installed, run:
::

    heroku --version


To install:
::

    brew install heroku/brew/heroku

More information on the Heroku CLI is available at `heroku.com <https://devcenter.heroku.com/articles/heroku-cli>`__ along with alternative installation instructions, if needed.


Install Redis
~~~~~~~~~~~~~

Debugging experiments requires you to have Redis installed and the Redis
server running.
::

    brew install redis

Start Redis on Mac OS X with:
::

    brew services start redis

You can find more details and other installation instructions at `redis.com <https://redis.io/topics/quickstart>`__.

Install Git
~~~~~~~~~~~

Dallinger uses Git, a distributed version control system, for version control of its code.
If you do not have it installed, you can install it as follows:

::

    brew install git


You will need to configure your Git name and email:

::

  git config --global user.email "you@example.com"
  git config --global user.name "Your Name"


Replace ``you@example.com`` and ``Your Name`` with your email and name to set your account's default identity.
Omit --global to set the identity only in this repository. You can read more about configuring Git `here <https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup/>`__.


Set up a virtual environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Why use virtualenv?

Virtualenv solves a very specific problem: it allows multiple Python projects
that have different (and often conflicting) requirements, to coexist on the same computer.
If you want to understand this in detail, you can read more about it `here <https://www.dabapps.com/blog/introduction-to-pip-and-virtualenv-python/>`__.

Now let's set up a virtual environment by running the following commands:
::


    pip3 install virtualenv
    pip3 install virtualenvwrapper
    export WORKON_HOME=$HOME/.virtualenvs
    mkdir -p $WORKON_HOME
    export VIRTUALENVWRAPPER_PYTHON=$(which python3.9)
    source $(which virtualenvwrapper.sh)


Now create the virtual environment using:
::


    mkvirtualenv dlgr_env --python <specify_your_python_path_here>


Example:
::


    mkvirtualenv dlgr_env --python /usr/local/bin/python3.9

Virtualenvwrapper provides an easy way to switch between virtual environments
by simply typing: ``workon [virtual environment name]``.

The technical details:

These commands use ``pip/pip3``, the Python package manager, to install two
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
you've named ``dlgr_env``. We have explicitly passed it the location of the Python
that the virtualenv should use. This Python has been mapped to the ``python``
command inside the virtual environment.

The how-to:

In the future, you can work on your virtual environment by running:
::

    export VIRTUALENVWRAPPER_PYTHON=$(which python3.9)
    source $(which virtualenvwrapper.sh)
    workon dlgr_env


NB: To stop working in the virtual environment, run ``deactivate``. To
list all available virtual environments, run ``workon`` with no
arguments.

If you plan to do a lot of work with Dallinger, you can make your shell
execute the ``virtualenvwrapper.sh`` script everytime you open a terminal. To
do that type:
::

    echo "export VIRTUALENVWRAPPER_PYTHON=$(which python3.9)" >> ~/.bash_profile
    echo "source $(which virtualenvwrapper.sh)" >> ~/.bash_profile


From then on, you only need to use the ``workon`` command before starting.

Install prerequisites for building documentation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To be able to build the documentation, you will need yarn.

Please follow the instructions `here <https://yarnpkg.com/lang/en/docs/install>`__  to install it.

Install Dallinger
~~~~~~~~~~~~~~~~~

Next, navigate to the directory where you want to house your development
work on Dallinger. Once there, clone the Git repository using:
::

    git clone https://github.com/Dallinger/Dallinger

This will create a directory called ``Dallinger`` in your current
directory.

Change into your the new directory and make sure you are still in your
virtual environment before installing the dependencies. If you want to
be extra careful, run the command ``workon dlgr_env``, which will ensure
that you are in the right virtual environment.

::

    cd Dallinger

Now we need to install the dependencies using pip:

::

    pip install -r dev-requirements.txt

You may see a large volume of warnings and errors, with this somewhere near the
bottom:

    ld: library not found for -lssl
    clang: error: linker command failed with exit code 1 (use -v to see invocation)
    error: command '/usr/bin/clang' failed with exit code 1

Try adding the paths of the SSL binaries, then installing again:

    export LDFLAGS="-L$(brew --prefix openssl)/lib"; export CPPFLAGS="-I$(brew --prefix openssl)/include"
    pip install -r dev-requirements.txt


Next, install the Dallinger development directory as an editable package, and include the ``data`` "extra":

::

    pip install --editable ".[data]"


Test that your installation works by running:

::

    dallinger --version

Install the Git pre-commit hook
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the virtual environment still activated:

::

    pip install pre-commit

This will install the pre-commit package into the virtual environment. With that
in place, each `git clone` of Dallinger you create will need to have the pre-commit
hook installed with:

::

    pre-commit install

This will install a pre-commit hook to check for flake8 violations, and enforce
a standard Python source code format via `black
<https://black.readthedocs.io/en/stable/>`__. You can run the `black` code
formatter and flake8 checks manually at any time by running:

::

    pre-commit run --all-files

You may also want to install a black plugin for your own code editor, though this is not strictly necessary, since the pre-commit hook will run `black` for you on commit.

Install the dlgr.demos sub-package
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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

Ubuntu
------

Install Python
~~~~~~~~~~~~~~

Dallinger is written in the language Python. For it to work, you will need
to have Python 3.9 or higher. Python 3 is the preferred option.
You can check what version of Python you have by running:
::

    python --version


Ubuntu 18.04 LTS ships with Python 3.6.

Ubuntu 16.04 LTS ships with Python 3.5, while Ubuntu 14.04 LTS ships with Python 3.4.
In case you are using one of these distributions of Ubuntu, you will need to
upgrade to the latest Python 3.x on your own.

If you do not have Python 3 installed, you can install it from the
`Python website <https://www.python.org/downloads/>`__.

Also make sure you have the python headers installed. The python-dev package
contains the header files you need to build Python extensions appropriate to the Python version you will be using.

.. note::

    You will also need to have `pip <https://pip.pypa.io/en/stable>`__ installed. It is included in some of the later versions of Python 3, but not all. (pip is a package manager for Python packages, or modules if you like.) If you are using Python 3, you may find that you may need to use the ``pip3`` command instead of ``pip`` where applicable in the instructions that follow.

::

    sudo apt-get install python3-dev
    sudo apt install -y python3-pip



Install Postgresql
~~~~~~~~~~~~~~~~~~

The lowest version of Postgresql that Dallinger v5 supports is 9.4.

This is fine for Ubuntu 18.04 LTS and 16.04 LTS as they
ship with Postgresql 10.4 and 9.5 respectively, however Ubuntu 14.04 LTS ships with Postgresql 9.3

Postgres can be installed using the following instructions:

**Ubuntu 18.04 LTS** or **Ubuntu 16.04 LTS:**
::

    sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib

To run postgres, use the following command:
::

    sudo service postgresql start


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


Create the databases
~~~~~~~~~~~~~~~~~~~~

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

Install Heroku
~~~~~~~~~~~~~~

To run experiments locally or on the internet, you will need the Heroku Command
Line Interface installed, version 3.28.0 or better. If you want to launch experiments on the internet, then
you will also need a Heroku.com account, however this is not needed for local debugging.

To check which version of the Heroku CLI you have installed, run:
::

    heroku --version


To install:
::

    sudo apt-get install curl
    curl https://cli-assets.heroku.com/install.sh | sh


More information on the Heroku CLI is available at `heroku.com <https://devcenter.heroku.com/articles/heroku-cli>`__ along with alternative installation instructions, if needed.

Install Redis
~~~~~~~~~~~~~

Debugging experiments requires you to have Redis installed and the Redis
server running.

::

    sudo apt-get install -y redis-server

Start Redis on Ubuntu with:
::

    sudo service redis-server start

You can find more details and other installation instructions at `redis.com <https://redis.io/topics/quickstart>`__.

Install Git
~~~~~~~~~~~

Dallinger uses Git, a distributed version control system, for version control of its code.
If you do not have it installed, you can install it as follows:

::

    sudo apt install git

You will need to configure your Git name and email:

::

  git config --global user.email "you@example.com"
  git config --global user.name "Your Name"


Replace ``you@example.com`` and ``Your Name`` with your email and name to set your account's default identity.
Omit --global to set the identity only in this repository. You can read more about configuring Git `here <https://git-scm.com/book/en/v2/Getting-Started-First-Time-Git-Setup/>`__.


Set up a virtual environment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Why use virtualenv?

Virtualenv solves a very specific problem: it allows multiple Python projects
that have different (and often conflicting) requirements, to coexist on the same computer.
If you want to understand this in detail, you can read more about it `here <https://www.dabapps.com/blog/introduction-to-pip-and-virtualenv-python/>`__.

Now let's set up a virtual environment by running the following commands:
::

    sudo pip3 install virtualenv
    sudo pip3 install virtualenvwrapper
    export WORKON_HOME=$HOME/.virtualenvs
    mkdir -p $WORKON_HOME
    export VIRTUALENVWRAPPER_PYTHON=/usr/bin/python3
    source /usr/local/bin/virtualenvwrapper.sh

.. note::

    If the last line failed with "No such file or directory". Try using ``source /usr/local/bin/virtualenvwrapper.sh`` instead. Pip installs `virtualenvwrapper.sh` to different locations depending on the Ubuntu version.


Now create the virtualenv using the ``mkvirtualenv`` command as follows:

If you are using Python 3 that is part of your Ubuntu installation (Ubuntu 18.04):
::

    mkvirtualenv dlgr_env --python /usr/bin/python3

If you are using Python 2 that is part of your Ubuntu installation:
::

    mkvirtualenv dlgr_env --python /usr/bin/python

If you are using another Python version
(eg. custom installed Python 3.x on Ubuntu 16.04 or Ubuntu 14.04):
::

    mkvirtualenv dlgr_env --python <specify_your_python_path_here>


Virtualenvwrapper provides an easy way to switch between virtual environments
by simply typing: ``workon [virtual environment name]``.

The technical details:

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
you've named ``dlgr_env``. We have explicitly passed it the location of the Python
that the virtualenv should use. This Python has been mapped to the ``python``
command inside the virtual environment.

The how-to:
::

    source /usr/local/bin/virtualenvwrapper.sh
    workon dlgr_env

NB: To stop working in the virtual environment, run ``deactivate``. To
list all available virtual environments, run ``workon`` with no
arguments.

If you plan to do a lot of work with Dallinger, you can make your shell
execute the ``virtualenvwrapper.sh`` script everytime you open a terminal. To
do that:
::

    echo "source /usr/local/bin/virtualenvwrapper.sh" >> ~/.bashrc

From then on, you only need to use the ``workon`` command before starting.

Install prerequisites for building documentation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

To be able to build the documentation, you will need yarn.

Please follow the instructions `here <https://yarnpkg.com/lang/en/docs/install>`__  to install it.

Install Dallinger
~~~~~~~~~~~~~~~~~

Next, navigate to the directory where you want to house your development
work on Dallinger. Once there, clone the Git repository using:
::

    git clone https://github.com/Dallinger/Dallinger

This will create a directory called ``Dallinger`` in your current
directory.

Change into your the new directory and make sure you are still in your
virtual environment before installing the dependencies. If you want to
be extra careful, run the command ``workon dlgr_env``, which will ensure
that you are in the right virtual environment.

::

    cd Dallinger

Now we need to install the dependencies using pip:

::

    pip install -r dev-requirements.txt


Next, install the Dallinger development directory as an editable package, and include the ``data`` "extra":

::

    pip install --editable .[data]


Test that your installation works by running:

::

    dallinger --version


Install the Git pre-commit hook
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the virtual environment still activated:

::

    pip install pre-commit

This will install the pre-commit package into the virtual environment. With that
in place, each `git clone` of Dallinger you create will need to have the pre-commit
hook installed with:

::

    pre-commit install

This will install a pre-commit hook to check for flake8 violations, and enforce
a standard Python source code format via `black
<https://black.readthedocs.io/en/stable/>`__. You can run the `black` code
formatter and flake8 checks manually at any time by running:

::

    pre-commit run --all-files

You may also want to install a black plugin for your own code editor, though this is not strictly necessary, since the pre-commit hook will run `black` for you on commit.

Install the dlgr.demos sub-package
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

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
