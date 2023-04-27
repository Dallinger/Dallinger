Running demos on Heroku
=======================

Running the demos of Dallinger in "sandbox" mode, will require a Heroku account and verification by providing a credit card in your Heroku account.
If you only make use of Heroku's free tier offerings, you will not be charged.

Heroku states that the use of any add-on requires account verification (even free tier add-ons). Redis is a requirement for Dallinger to run and is considered by Heroku as an add-on feature.
More information on account verification can be found `here <https://devcenter.heroku.com/articles/account-verification/>`__.

If you wish to only make use of Heroku's free tier offerings, set the following in the demo's config.txt file:
::

    database_size = standard-0
    redis_size = premium-0


You can read more about Heroku's `Postgres Plans <https://devcenter.heroku.com/articles/heroku-postgres-plans/>`__ and
their `Redis add-on <https://elements.heroku.com/addons/heroku-redis/>`__ offering.

Also note that you may also need to set:
::

    dyno_type = basic

Read more about Heroku's `Dyno Types <https://devcenter.heroku.com/articles/dyno-types/>`__.
