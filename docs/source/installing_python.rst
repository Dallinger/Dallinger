Installing Python
===================


OSX
~~~

Using Homebrew will install the latest version of Python and pip by default.

::

    brew install python

This will install the latest Python3 and pip3.

You can also use the preinstalled Python in OSX, currently Python 2.7 as of writing.

If you installed Python 3 with Homebrew, you should now be able to run the ``python3`` command from the terminal.
If the command cannot be found, check the Homebrew installation log to see
if there were any errors. Sometimes there are problems symlinking Python 3 to 
the python3 command. If this is the case for you, look `here <https://stackoverflow.com/questions/27784545/brew-error-could-not-symlink-path-is-not-writable>`__ for clues to assist you.

With the preinstalled Python in OSX, you will need to install pip yourself. You can use:
::

    sudo easy_install pip


Should that not work for whatever reason, you can search `here <https://docs.python-guide.org/>`__ for more clues.


Ubuntu
~~~~~~

Ubuntu 18.04 LTS ships with Python 3.6.

Ubuntu 16.04 LTS ships with Python 3.5, while Ubuntu 14.04 LTS ships with Python 3.4. In case you are using these distribution of Ubuntu, you can use
dallinger with Python 2.7 or upgrade to the latest Python 3.x on your own.

(All three of these Ubuntu versions also provide a version of Python 2.7)

If you do not have Python 3 installed, you can install it from the
`Python website <https://www.python.org/downloads/>`__.

Also make sure you have the python headers installed. The python-dev package
contains the header files you need to build Python extensions appropriate to the Python version you will be using.
You will also need to install pip.

If using Python 2.7.x:
::

    sudo apt-get install python-dev
    sudo apt install -y python-pip

If using Python 3.x:
::

    sudo apt-get install python3-dev
    sudo apt install -y python3-pip


Anaconda
~~~~~~~~
::

    conda install python
