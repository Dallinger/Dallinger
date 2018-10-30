Developer Installation
======================

We recommend installing Dallinger on Mac OS X. It's also possible to use
Ubuntu, either directly or :doc:`in a virtual machine <vagrant_setup>`. Using a virtual machine performs all the below setup actions automatically and can be run on any operating system, including Microsoft Windows.

You can also install Dallinger using :doc:`Docker <docker_setup>`.

Install Python
--------------

It recommended that you run Dallinger on Python 3. Dallinger has been tested to work on Python 3.6 and up.
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

Follow the :doc:`Create the databases instructions <creating_databases>`.

Install Heroku and Redis
------------------------

Follow the :doc:`Heroku and Redis installation instructions <heroku_redis>`.

Set up a virtual environment
----------------------------

Follow the :doc:`Virtual environment setup instructions <setup_virtualenv>`.

**Note**: if you are using Anaconda, ignore this ``virtualenv``
section; use ``conda`` to create your virtual environment. Or, see the
special :doc:`Anaconda installation instructions <dallinger_with_anaconda>`.

Install prerequisites for building documentation
------------------------------------------------

To be able to build the documentation, you will need yarn.

Please follow the instructions `here <https://yarnpkg.com/lang/en/docs/install>`__  to install it.

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
be extra careful, run the command ``workon dlgr_env``, which will ensure
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
