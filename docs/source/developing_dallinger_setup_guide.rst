Developer Installation
======================

We recommend installing Dallinger on Mac OS X. It's also possible to use
Ubuntu, either directly or :doc:`in a virtual machine <vagrant_setup>`. Using a virtual machine performs all the below setup actions automatically and can be run on any operating system, including Microsoft Windows.

Install Python 2.7
------------------

You will need Python 2.7. You can check what version of Python you have
by running:

::

    python --version

If you do not have Python 2.7 installed, you can install it from the
`Python website <https://www.python.org/downloads/>`__.

Or, if you use Homebrew:

::

    brew install python

Or, if you use Anaconda, install using ``conda``, not Homebrew.

If you have Python 3.\ *x* installed and and symlinked to the command
``python``, you will need to create a ``virtualenv`` that interprets the
code as ``python2.7``.
Fortunately, we will be creating a virtual environment anyway, so as
long as you run ``brew install python`` and you don't run into any
errors because of your symlinks, then you can proceed with the
instructions. If you do run into any errors, good luck, we're rooting
for you.

Install Postgres
----------------

On OS X, we recommend installing
`Postgres.app <http://postgresapp.com>`__ to start and stop a Postgres
server. You'll also want to set up the Postgres command-line utilities
by following the instructions
`here <http://postgresapp.com/documentation/cli-tools.html>`__.

You will then need to add Postgres to your PATH environmental variable.
If you use the default location for installing applications on OS X
(namely ``/Applications``), you can adjust your path by running the
following command:

::

    export PATH="$PATH:/Applications/Postgres.app/Contents/Versions/latest/bin"

NB: If you have installed an older version of Postgres (e.g., < 9.5),
you may need to alter that command to accommodate the more recent
version number. To double check which version to include, run:

::

    ls /Applications/Postgres.app/Contents/Versions/

Whatever values that returns are the versions that you should place in
the ``export`` command above in the place of ``latest``.

If it does not return a number, you have not installed Postgres
correctly in your ``/Applications`` folder or something else is horribly
wrong.

On Ubuntu, follow the instructions under the heading "Installation"
`here <https://help.ubuntu.com/community/PostgreSQL>`__.

Create the Database
-------------------

After installing Postgres, you will need to create a database for your
experiments to use. First, open the Postgres.app. Then, run the
following command from the command line:

::

    psql -c 'create database dallinger;' -U postgres

If you get the following error...

::

    psql: could not connect to server: No such file or directory
        Is the server running locally and accepting
        connections on Unix domain socket "/tmp/.s.PGSQL.5432"?

...then you probably did not start the app.

If you get the following error...

::

    dyld: Library not loaded: /usr/local/opt/readline/lib/libreadline.6.dylib
        Referenced from: /usr/local/bin/psql
        Reason: image not found
    Abort trap: 6

... then type the following command into the command line:

::

    createdb -U postgres dallinger
    
(This error may arise if you are running Python 2.7 with Anaconda within a virtual environment.)

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
    mkvirtualenv dallinger --python /usr/local/bin/python2.7

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
``python2.7`` so that even if your ``python`` command has been remapped
to ``python3``, it will create the environment with ``python2.7`` as its
interpreter.

In the future, you can work on your virtual environment by running:

::

    source $(which virtualenvwrapper.sh)
    workon dallinger

NB: To stop working on the virtual environment, run ``deactivate``. To
list all available virtual environments, run ``workon`` with no
arguments.

Install prerequisites for building documentation
------------------------------------------------

To be able to build the documentation, you will need:

* pandoc. Please follow the instructions `here
  <http://pandoc.org/installing.html>`__ to install it.
* the Enchant library. Please follow the instructions `here
  <http://pythonhosted.org/pyenchant/download.html>`__ to install it.

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

Next, you'll need :doc:`access keys for AWS, Heroku,
etc. <aws_etc_keys>`.
