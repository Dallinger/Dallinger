Installing Dallinger with Anaconda
==================================

If you are interested in Dallinger and use
`Anaconda <https://www.continuum.io/downloads>`__, you'll need to adapt
the standard instructions slightly.


Install psycopg2
----------------

In order to get the correct bindings, you need to install ``psycopg2`` before
installing Dallinger.

::

    conda install psycopg2
    conda install Dallinger[data]

The `[data]` optional extra makes sure that all the data analysis dependencies
are installed.

Confirm Dallinger works
-----------------------

Now, we need to make sure that Dallinger and Anaconda play nice with one
another. At this point, we'd check to make sure that Dallinger is properly
installed by typing

::

    dallinger --version


into the command line. You may get a long
error message. Don't panic! Add the following to your ``.bash_profile``:

::

    export DYLD_FALLBACK_LIBRARY_PATH=$HOME/anaconda/lib/:$DYLD_FALLBACK_LIBRARY_PATH

After you ``source`` your ``.bash_profile``, you can check your Dallinger
version (using the same command that we used earlier), which should
return the Dallinger version that you've installed.

Re-link Open SSL
----------------

Finally, you'll need to re-link ``openssl``. Run the following:

::

    brew install --upgrade openssl
    brew unlink openssl && brew link openssl --force
