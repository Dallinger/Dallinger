Set up a virtual environment
============================

First, make sure you have Python installed:

-  :doc:`installing_python`


Set up a virtualenv
-------------------

Why?

Virtualenv solves a very specific problem: it allows multiple Python projects
that have different (and often conflicting) requirements, to coexist on the same computer.
If you want to understand this in detail, you can read more about it `here <https://www.dabapps.com/blog/introduction-to-pip-and-virtualenv-python/>`__.

Now let's set up a virtual environment by running the following commands:

OSX
~~~

If using Python 2.7 and pip:
::


    pip install virtualenv
    pip install virtualenvwrapper
    export WORKON_HOME=$HOME/.virtualenvs
    mkdir -p $WORKON_HOME
    export VIRTUALENVWRAPPER_PYTHON=$(which python)
    source $(which virtualenvwrapper.sh)

If using Python 3.x and pip3 (Python 3.7 in this example):
::


    pip3 install virtualenv
    pip3 install virtualenvwrapper
    export WORKON_HOME=$HOME/.virtualenvs
    mkdir -p $WORKON_HOME
    export VIRTUALENVWRAPPER_PYTHON=$(which python3.7)
    source $(which virtualenvwrapper.sh)


Now create the virtual environment using:
::


    mkvirtualenv dlgr_env --python <specify_your_python_path_here>


Examples:

Using homebrew installed Python 3.7:
::


    mkvirtualenv dlgr_env --python /usr/local/bin/python3.7

Using Python 2.7:
::


    mkvirtualenv dlgr_env --python /usr/bin/python


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
Python 2.7
::

    export VIRTUALENVWRAPPER_PYTHON=$(which python)
    source $(which virtualenvwrapper.sh)
    workon dlgr_env

Python 3.x
::

    export VIRTUALENVWRAPPER_PYTHON=$(which python3.7)
    source $(which virtualenvwrapper.sh)
    workon dlgr_env


NB: To stop working in the virtual environment, run ``deactivate``. To
list all available virtual environments, run ``workon`` with no
arguments.

If you plan to do a lot of work with Dallinger, you can make your shell
execute the ``virtualenvwrapper.sh`` script everytime you open a terminal. To
do that type:

Python 2.7
::

    echo "export VIRTUALENVWRAPPER_PYTHON=$(which python)" >> ~/.bash_profile
    echo "source $(which virtualenvwrapper.sh)" >> ~/.bash_profile

Python 3.x
::

    echo "export VIRTUALENVWRAPPER_PYTHON=$(which python3.7)" >> ~/.bash_profile
    echo "source $(which virtualenvwrapper.sh)" >> ~/.bash_profile


From then on, you only need to use the ``workon`` command before starting.

Ubuntu
~~~~~~
::

    sudo pip install virtualenv
    sudo pip install virtualenvwrapper
    export WORKON_HOME=$HOME/.virtualenvs
    mkdir -p $WORKON_HOME
    source /usr/local/bin/virtualenvwrapper.sh

Now create the virtualenv using the ``mkvirtualenv`` command as follows:

If you are using Python 3 that is part of your Ubuntu installation (16.04 or 18.04):
::

    mkvirtualenv dlgr_env --python /usr/bin/python3

If you are using Python 2 that is part of your Ubuntu installation:
::

    mkvirtualenv dlgr_env --python /usr/bin/python

If you are using another Python version 
(eg. custom installed Python 3.x on Ubuntu 14.04):
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

In the future, you can work on your virtual environment by running:
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
