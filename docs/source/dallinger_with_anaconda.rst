Installing Dallinger with Anaconda
==================================

If you are interested in Dallinger and use
`Anaconda <https://www.continuum.io/downloads>`__, you'll need to adapt
the standard instructions slightly.

Getting Python 2.7 started if you have Anaconda 3
----------------

If you have Anaconda 3 (i.e., Anaconda running Python 3), you'll need to create a virtual environment for Python 2.7.

To initialize the new environment, type the following command into the command line:

::

    conda create -n py27 python=2.7 anaconda

You can customize the name of your Python 2.7 environment by changing the ``py27`` to your environment name of choice. Once it's created, then activate your new environment at the command line:

::

    source activate py27

If you didn't choose to stick with the ``py27`` name, make sure that you change that to reflect your environment name. Once you've activated the environment, you can proceed with the rest of the instructions below.

Whenever you want to leave the environment, you can deactivate it at the command line:

::
    source deactivate py27

Again, be sure to change ``py27`` to whatever you called your environment.

For more information about creating virtual environments within Anaconda, check out [http://conda.pydata.org/docs/using/envs.html].

Install psycopg2
----------------

In order to get the correct bindings, you need to install ``psycopg2``
before you use ``requirements.txt``; otherwise, everything will fail and
you will be endlessly frustrated.

::

    conda install psycopg2

Install Dallinger
-----------------

You'll follow all of the :doc:`Dallinger development installation
instructions <developing_dallinger_setup_guide>`,
**with the exception of the virtual environment step**.  Then return here.

Confirm Dallinger works
-----------------------

Now, we need to make sure that Dallinger and Anaconda play nice with one
another. At this point, we'd check to make sure that Dallinger is properly
installed by typing

::

    dallinger --version

into the command line. For those of us with Anaconda, we'll get a long
error message. Don't panic! Add the following to your ``.bash_profile``:

::

    export DYLD_FALLBACK_LIBRARY_PATH=$HOME/anaconda/lib/:$DYLD_FALLBACK_LIBRARY_PATH

If you installed anaconda using ``Python 3``, you will need to change
``anaconda`` in that path to ``anaconda3``.

After you ``source`` your ``.bash_profile``, you can check your Dallinger
version (using the same command that we used earlier), which should
return the Dallinger version that you've installed.

Re-link Open SSL
----------------

Finally, you'll need to re-link ``openssl``. Run the following:

::

    brew install --upgrade openssl
    brew unlink openssl && brew link openssl --force
