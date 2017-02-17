Configuration
=============

The Dallinger ``configuration`` module provides tools for reading and writing
configuration parameters that control the behavior of an experiment. To use the
configuration, first import the module and get the configuration object:

::

    import dallinger

    config = dallinger.config.get_config()

You can then get and set parameters:

::

    config.get("duration")
    config.set("duration", 0.50)

When retrieving a configuration parameter, Dallinger will look for the parameter
first among environment variables, then in a ``config.txt`` in the experiment
directory, and then in the ``.dallingerconfig`` file, using whichever value
is found first. If the parameter is not found, Dallinger will use the default.

Built-in configuration
----------------------

Built-in configuration parameters include:

``mode``
    Run the experiment in this mode. Options include ``debug`` (local testing),
    ``sandbox`` (MTurk sandbox), and ``live`` (MTurk).

``title``
    Title of the HIT on Amazon Mechanical Turk.

``description``
    Description of the HIT on Amazon Mechanical Turk.

``keywords``
    Comma-separated list of keywords to use on Amazon Mechanical Turk.

``lifetime``
    How long in hours that your HIT remains visible to workers.

``duration``
    How long in hours participants have until the HIT will time out.

``us_only``
    A boolean that control whether this HIT is available only to MTurk workers
    in the U.S.

``base_payment``
    Base payment in U.S. dollars.

``approve_requirement``
    The percentage of past MTurk HITs that must have been approved for a worker
    to qualify to participate in your experiment. 1-100.

``contact_email_on_error`` *unicode*
    Email address displayed when there is an error.

``auto_recruit``
    Whether recruitment should be automatic.

``group``
    A string. *Unicode string*.

``loglevel``
    A number between 0 and 4 that controls the verbosity of logs, from ``debug``
    to ``critical``.

``organization_name`` [string]
    Identifies your institution, business, or organization.

``browser_exclude_rule`` [comma separated string]
    A set of rules you can apply to prevent participants with unsupported web
    browsers from participating in your experiment.

``database_url``
    URI of the Postgres database.

``database_size``
    Size of the database on Heroku. See `Heroku Postgres plans <https://devcenter.heroku.com/articles/heroku-postgres-plans>`__.

``dyno_type``
    Heroku dyno type to use. See `Heroku dynos types <https://devcenter.heroku.com/articles/dyno-types>`__.

``num_dynos_web``
    Number of Heroku dynos to use for processing incoming HTTP requests. It is
    recommended that you use at least two.

``num_dynos_worker``
    Number of Heroku dynos to use for performing other computations.

``host``
    IP address of the host.

``port``
    Port of the host.

``notification_url``
    URL where notifications are sent. This should not be set manually.

``clock_on``
    If the clock process is on, it will perform a series of checks that ensure
    the integrity of the database.

``logfile``
    Where to write logs.

``aws_access_key_id``
    AWS access key ID.

``aws_secret_access_key``
    AWS access key secret.

``aws_region``
    AWS region to use. Defaults to ``us-east-1``.

``dallinger_email_address``
    A Gmail address for use by Dallinger to send status emails.

``dallinger_email_password``
    Password for the aforementioned Gmail address.

``heroku_team``
    The name of the Heroku team to which all applications will be assigned.
    This is useful for centralized billing. Note, however, that it will prevent
    you from using free-tier dynos.

``whimsical``
    What's life without whimsy?
