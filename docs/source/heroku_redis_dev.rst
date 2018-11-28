Installing Heroku and Redis
===========================

Install Heroku
--------------

To run experiments locally or on the internet, you will need the Heroku Command
Line Interface installed, version 3.28.0 or better. If you want to launch experiments on the internet, then
you will also need a Heroku.com account, however this is not needed for local debugging.

To check which version of the Heroku CLI you have installed, run:
::

    heroku --version

The Heroku CLI is available for download from
`heroku.com <https://devcenter.heroku.com/articles/heroku-cli>`__.

Install Redis
-------------

Debugging experiments requires you to have Redis installed and the Redis
server running.

Mac OS X
~~~~~~~~
::

    brew install redis

Start Redis on Mac OS X with:
::

    brew services start redis

Ubuntu
~~~~~~
::

    sudo apt-get install -y redis-server

Start Redis on Ubuntu with:
::

    sudo service redis-server start

You can find more details and other installation instructions at `redis.com <https://redis.io/topics/quickstart>`__.

