Set up a virtual environment
============================

First, make sure you have Python installed:

-  :doc:`installing_python`


Set up a virtualenv
-------------------

Set up a virtual environment by running the following commands:

OSX
~~~
::

    pip install virtualenv
    pip install virtualenvwrapper
    export WORKON_HOME=$HOME/.virtualenvs
    mkdir -p $WORKON_HOME
    source $(which virtualenvwrapper.sh)
    mkvirtualenv dlgr_env --python /usr/local/bin/python3.6

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
you've named ``dlgr_env``. We have explicitly passed it the location of
``python3.6`` so that even if your ``python`` command has been remapped
to ``python2.7``, it will create the environment with ``python3.6`` as its
interpreter.

In the future, you can work on your virtual environment by running:
::

    source $(which virtualenvwrapper.sh)
    workon dlgr_env

NB: To stop working on the virtual environment, run ``deactivate``. To
list all available virtual environments, run ``workon`` with no
arguments.

If you plan to do a lot of work with Dallinger, you can make your shell
execute the ``virtualenvwrapper.sh`` script everytime you open a terminal. To
do that type:
::

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

Finally if you are using Python 3 that came with your Ubuntu installation (16.04 or 18.04)
::

    mkvirtualenv dlgr_env --python /usr/bin/python3

If you are using Python 2 that came with your installation
::

    mkvirtualenv dlgr_env --python /usr/bin/python

If you are using another python (eg custom installed Python 3.x on Ubuntu 14.04)
::

    mkvirtualenv dlgr_env --python <specify_your_python_path_here>

Note that the last line uses Python 2 and not Python 3 as the system python3 in Ubuntu 14.04 LTS
is Python 3.4. If you install your own Python 3.5 or higher, change the last line to point to
the location where you installed that Python.

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
you've named ``dlgr_env``. We have explicitly passed it the location of the python
that the virtualenv should use inside it.

In the future, you can work on your virtual environment by running:
::

    source /usr/local/bin/virtualenvwrapper.sh
    workon dlgr_env

NB: To stop working on the virtual environment, run ``deactivate``. To
list all available virtual environments, run ``workon`` with no
arguments.

If you plan to do a lot of work with Dallinger, you can make your shell
execute the ``virtualenvwrapper.sh`` script everytime you open a terminal. To
do that:
::

    echo "source /usr/local/bin/virtualenvwrapper.sh" >> ~/.bashrc

From then on, you only need to use the ``workon`` command before starting.
