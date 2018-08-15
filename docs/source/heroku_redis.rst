Installing Heroku and Redis
===========================

Install Heroku
--------------

To run experiments locally or on the internet, you will need the Heroku Command
Line Interface installed, version 3.28.0 or better. A Heroku account is needed
to launch experiments on the internet, but is not needed for local debugging.

To check which version of the Heroku CLI you have installed, run:
::

    heroku --version

The Heroku CLI is available for download from
`heroku.com <https://devcenter.heroku.com/articles/heroku-cli>`__.

Install Redis
-------------

Debugging experiments requires you to have Redis installed and the Redis
server running.

OSX
~~~
::

    brew install redis-service

Start Redis on OSX with:
::

    redis-server

Ubuntu
~~~~~~
::

    sudo apt-get install -y redis-server

Start Redis on Ubuntu with:
::

    sudo service redis-server start

You can find more details and other installation instructions at `redis.com <https://redis.io/topics/quickstart>`__.

