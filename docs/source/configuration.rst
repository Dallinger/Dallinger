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

If a value is extracted from the environment or a config file it will be converted
to the correct type. You can also specify a value of ``file:/path/to/file`` to
use the contents of that file on your local computer.


Built-in configuration
----------------------

Built-in configuration parameters, grouped into categories:

General
~~~~~~~

``mode`` *unicode*
    Run the experiment in this mode. Options include ``debug`` (local testing),
    ``sandbox`` (MTurk sandbox), and ``live`` (MTurk).

``logfile`` *unicode*
    Where to write logs.

``loglevel`` *unicode*
    A number between 0 and 4 that controls the verbosity of logs, from ``debug``
    to ``critical``. Note that ``dallinger debug`` ignores this setting and always
    runs at 0 (``debug``).

``whimsical`` *boolean*
    What's life without whimsy? Controls whether email notifications sent
    regarding various experiment errors are whimsical in tone, or more
    matter-of-fact.

``dallinger_develop_directory`` *unicode*
    The directory on your computer to be used to hold files and symlinks
    when running ``dallinger develop``. Defaults to ``~/dallinger_develop``
    (a folder named ``dallinger_develop`` inside your home directory).

``dashboard_password`` *unicode*
    An optional password for accessing the Dallinger Dashboard interface. If not
    specified, a random password will be generated.

``dashboard_user`` *unicode*
    An optional login name for accessing the Dallinger Dashboard interface. If not
    specified ``admin`` will be used.

``protected_routes`` *unicode - JSON formatted*
    An optional JSON array of Flask route rule names which should be made inaccessible.
    Example::

        protected_routes = ["/participant/<participant_id>", "/network/<network_id>", "/node/<int:node_id>/neighbors"]

    Accessing routes included in this list will raise a PermissionError
    and no data will be returned.

``enable_global_experiment_registry`` *boolean*
    Enable a global experiment id registration. When enabled, the ``collect`` API
    check this registry to see if an experiment has already been run and reject
    re-running an experiment if it has been.

``language`` *unicode*
    A ``gettext`` language code to be used for the experiment.


Recruitment (General)
~~~~~~~~~~~~~~~~~~~~~

``activate_recruiter_on_start`` *boolean*
    A boolean on whether recruitment should start automatically when the experiment launches.
    If set to ``false`` the user has to manually initialize recruitment (e.g. via the Prolific panel).
    Defaults to ``true``.

``auto_recruit`` *boolean*
    A boolean on whether recruitment should be automatic.

``browser_exclude_rule`` *unicode - comma separated*
    A set of rules you can apply to prevent participants with unsupported web
    browsers from participating in your experiment. Valid exclustion values are:

        * mobile
        * tablet
        * touchcapable
        * pc
        * bot

``recruiter`` *unicode*
    The recruiter class to use during the experiment run. While this can be a
    full class name, it is more common to use the class's ``nickname`` property
    for this value; for example ``mturk``, ``prolific``, ``cli``, ``bots``,
    or ``multi``.

    NOTE: when running in debug mode, the HotAir (``hotair``) recruiter will
    always be used. The exception is if the ``--bots`` option is passed to
    ``dallinger debug``, in which case the BotRecruiter will be used instead.

``recruiters`` *unicode - custom format*
    When using multiple recruiters in a single experiment run via the ``multi``
    setting for the ``recruiter`` config key, ``recruiters`` allows you to
    specify which recruiters you'd like to use, and how many participants to
    recruit from each. The special syntax for this value is:

    ``recruiters = [nickname 1]: [recruits], [nickname 2]: [recruits], etc.``

    For example, to recruit 5 human participants via MTurk, and 5 bot participants,
    the configuration would be:

    ``recruiters = mturk: 5, bots: 5``


Amazon Mechanical Turk Recruitment
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``aws_access_key_id`` *unicode*
    AWS access key ID.

``aws_secret_access_key`` *unicode*
    AWS access key secret.

``aws_region`` *unicode*
    AWS region to use. Defaults to ``us-east-1``.

``ad_group`` *unicode*
    Obsolete. See ``group_name``.

``assign_qualifications`` *boolean*
    A boolean which controls whether an experiment-specific qualification
    (based on the experiment ID), and a group qualification (based on the value
    of ``group_name``) will be assigned to participants by the recruiter.
    This feature assumes a recruiter which supports qualifications,
    like the ``MTurkRecruiter``.

``group_name`` *unicode*
    Assign a named qualification to workers who complete a HIT.

``mturk_qualification_blocklist`` *unicode - comma seperated*
    Comma-separated list of qualification names. Workers with qualifications in
    this list will be prevented from viewing and accepting the HIT.

``mturk_qualification_requirements`` *unicode - JSON formatted*
    A JSON list of qualification documents to pass to Amazon Mechanical Turk.

``title`` *unicode*
    The title of the HIT on Amazon Mechanical Turk.

``description`` *unicode*
    The description of the HIT on Amazon Mechanical Turk.

``keywords`` *unicode*
    A comma-separated list of keywords to use on Amazon Mechanical Turk.

``lifetime`` *integer*
    How long in hours that your HIT remains visible to workers.

``duration`` *float*
    How long in hours participants have until the HIT will time out.

``disable_when_duration_exceeded`` *boolean*
    Whether to disable recruiting and expire the HIT when the duration has been
    exceeded. This only has an effect when ``clock_on`` is enabled.

``us_only`` *boolean*
    Controls whether this HIT is available only to MTurk workers in the U.S.

``base_payment`` *float*
    Base payment in U.S. dollars. All workers who accept the HIT are guaranteed
    this much compensation.

``approve_requirement`` *integer*
    The percentage of past MTurk HITs that must have been approved for a worker
    to qualify to participate in your experiment. 1-100.

``organization_name`` *unicode*
    Obsolete.

Preventing Repeat Participants on MTurk
"""""""""""""""""""""""""""""""""""""""

If you set a ``group_name`` and ``assign_qualifications`` is also set to
``true``, workers who complete your HIT will be given an MTurk qualification for
your ``group_name``. In the future, you can prevent these workers from
participating in a HIT with the same ``group_name`` by including that name in
the ``qualification_blacklist`` configuration. These four configuration keys
work together to create a system to prevent recuiting workers who have already
completed a prior run of the same experiment.


.. _prolific-recruitment:

Prolific Recruitment
~~~~~~~~~~~~~~~~~~~~

``title`` *unicode*
    The title of the Study on Prolific

``description`` *unicode*
    The description of the Study on Prolific

``prolific_api_token`` *unicode*
    Your Prolific API token

    These are requested from Prolific via email or some other non-programmatic
    channel, and should be stored in your ``~/.dallingerconfig`` file.

``prolific_api_version`` *unicode*
    The version of the Prolific API you'd like to use

    The default ("v1") is defined in global_config_defaults.txt

``prolific_estimated_completion_minutes`` *int*
    Estimated duration in minutes of the experiment or survey

``prolific_recruitment_config`` *unicode - JSON formatted*
    JSON data to add additional recruitment parameters

    Since some recruitment parameters are complex and are defined with relatively complex
    syntax, Dallinger allows you to define this configuration in raw JSON. The parameters
    you would typically specify this way :ref:`include <json-config-disclaimer>`:

        - ``device_compatibility``
        - ``peripheral_requirements``
        - ``eligibility_requirements``

    See the `Prolific API Documentation <https://docs.prolific.com/docs/api-docs/public/#tag/Studies/paths/~1api~1v1~1studies~1/post>`__
    for details.

    Configuration can also be stored in a separate JSON file, and included by using the
    filename, prefixed with ``file:``, as the configuration value. For example, to use a
    JSON file called ``prolific_config.json``, you would first create this file, with
    valid JSON as contents::

        {
            "eligibility_requirements": [
                {
                    "attributes": [
                        {
                            "name": "white_list",
                            "value": [
                                # worker ID one,
                                # worker ID two,
                                # etc.
                            ]
                        }
                    ],
                    "_cls": "web.eligibility.models.CustomWhitelistEligibilityRequirement"
                }
            ]
        }


    You can also specify the devices you expect the participants to have, e.g.::

        {
            "eligibility_requirements": […],
            "device_compatibility": ["desktop"],
            "peripheral_requirements": ["audio", "microphone"]
        }

    Supported devices are ``desktop``, ``tablet``, and ``mobile``. Supported peripherals are ``audio``, ``camera``, ``download`` (download additional software to run the experiment), and ``microphone``.

    You would then include this file in your overall configuration by adding the following
    to your config.txt file::

        prolific_recruitment_config = file:prolific_config.json

    .. _json-config-disclaimer:

    A word of caution: while it is technically possible to specify other recruitment values this way
    (for example, ``{"title": "My Experiment Title"}``), we recommend that you stick to the standard
    key = value format of ``config.txt`` whenever possible, and leave ``prolific_recruitment_config``
    for complex requirements which can't be configured in this simpler way.

.. deprecated:: 10.0.0

    ``prolific_maximum_allowed_minutes`` *int*
        Max time in minutes for a participant to finish the submission

        Has no effect as it is currently ignored by the Prolific API.

.. note::

    Prolific will use the currency of your researcher account, and convert automatically
    to the participant's currency.


Email Notifications
~~~~~~~~~~~~~~~~~~~

See :doc:`Email Notification Setup <email_setup>` for a much more detailed
explanation of these values and their use.

``contact_email_on_error`` *unicode*
    The email address used as the recipient for error report emails, and the email displayed to workers when there is an error.

``dallinger_email_address`` *unicode*
    An email address for use by Dallinger to send status emails.

``smtp_host`` *unicode*
    Hostname and port of a mail server for outgoing mail. Defaults to ``smtp.gmail.com:587``

``smtp_username`` *unicode*
    Username for outgoing mail host.

``smtp_password`` *unicode*
    Password for the outgoing mail host.


Deployment Configuration
~~~~~~~~~~~~~~~~~~~~~~~~

``database_url`` *unicode*
    URI of the Postgres database.

``database_size`` *unicode*
    Size of the database on Heroku. See `Heroku Postgres plans <https://devcenter.heroku.com/articles/heroku-postgres-plans>`__.

``dyno_type`` *unicode*
    Heroku dyno type to use. See `Heroku dynos types <https://devcenter.heroku.com/articles/dyno-types>`__.

``redis_size`` *unicode*
    Size of the redis server on Heroku. See `Heroku Redis <https://elements.heroku.com/addons/heroku-redis>`__.

``num_dynos_web`` *integer*
    Number of Heroku dynos to use for processing incoming HTTP requests. It is
    recommended that you use at least two.

``num_dynos_worker`` *integer*
    Number of Heroku dynos to use for performing other computations,
    or (when deploying via Docker SSH) the number of worker Docker containers.

``host`` *unicode*
    IP address of the host.

``port`` *unicode*
    Port of the host.

``clock_on`` *boolean*
    If the clock process is on, it will enable a task scheduler to run automated
    background tasks. By default, a single task is registered which performs a
    series of checks that ensure the integrity of the database. The configuration
    option ``disable_when_duration_exceeded`` configures the behavior of that task.

``heroku_python_version`` *unicode*
    The python version to be used on Heroku deployments. The version specification will
    be deployed to Heroku in a `runtime.txt` file in accordance with Heroku's deployment
    API. Note that only the version number should be provided (eg: "2.7.14") and not the
    "python-" prefix included in the final `runtime.txt` format.
    See Dallinger's `global_config_defaults.txt` for the current default version.
    See `Heroku supported runtimes <https://devcenter.heroku.com/articles/python-support#supported-runtimes>`__.

``heroku_team`` *unicode*
    The name of the Heroku team to which all applications will be assigned.
    This is useful for centralized billing. Note, however, that it will prevent
    you from using free-tier dynos.

``worker_multiplier`` *float*
    Multiplier used to determine the number of gunicorn web worker processes
    started per Heroku CPU count. Reduce this if you see Heroku warnings
    about memory limits for your experiment. Default is `1.5`


Choosing configuration values
-----------------------------

When running real experiments it is important to pick configuration variables that
result in a deployment that performs appropriately.

The number of Heroku dynos that are required and their specifications can make a
very large difference to how the application behaves.

``num_dynos_web``
    This configuration variable determines how many dynos are run to deal with
    web traffic. They will be transparently load-balanced, so the more web dynos are
    started the more simultaneous HTTP requests the stack can handle.
    If an experiment defines the ``channel`` variable to subscribe to websocket events
    then all of these callbacks happen on the dyno that handles the initial ``/launch``
    POST, so experiments that use this functionality heavily receive significantly
    less benefit from increasing ``num_dynos_web``.
    The optimum value differs between experiments, but a good rule of thumb is 1 web
    dyno for every 10-20 simultaneous human users.

``num_dynos_worker``
    Workers are dynos that pull tasks from a queue and execute them in the background.
    They are optimized for many short tasks, but they are also used to run bots which
    are very long-lived. Each worker can run up to 20 concurrent tasks, however they
    are co-operatively multitasked so a poorly behaving task can cause all others
    sharing its host to block.
    When running with bots, you should always pick a value of ``num_dynos_worker` that
    is at least ``0.05*number_of_bots``, otherwise it is guaranteed to fail. In practice,
    there may well be experiment-specific tasks that also need to execute, and bots are
    more performant on underloaded dynos, so a better heuristic is ``0.25*number_of_bots``.

``dyno_type``
    This determines how powerful the heroku dynos started by Dallinger are. It is applied
    as the default for both web and worker dyno types. The minimum recommended is
    ``standard-1x``, which should be sufficient for experiments that do not rely on
    real-time coordination, such as :doc:`demos/bartlett1932/index`. Experiments that
    require significant power to process websocket events should consider the higher
    levels, ``standard-2x``, ``performance-m`` and ``performance-l``. In all but the
    most intensive experiments, either ``dyno_type`` or ``num_dynos_web`` should be
    increased, not both. See ``dyno_type_web`` and ``dyno_type_worker`` below
    for information about more specific settings.

``dyno_type_web``
    This determines how powerful the heroku web dynos are. It applies only to web dynos
    and will override the default set in ``dyno_type``. See ``dyno_type`` above for details
    on specific values.

``dyno_type_worker``
    This determines how powerful the heroku worker dynos are. It applies only to worker
    dynos and will override the default set in ``dyno_type``.. See ``dyno_type`` above for
    details on specific values.

``redis_size``
    A larger value for this increases the number of connections available on the redis dyno.
    This should be increased for experiments that make substantial use of websockets. Values
    are ``premium-0`` to ``premium-14``. It is very unlikely that values higher than ``premium-5``
    are useful.

``duration``
    The duration parameter determines the number of hours that an MTurk worker has to complete
    the experiment. Choosing numbers that are too short can cause people to refuse to work on
    a HIT. A deadline that is too long may give people pause for thought as it may make
    the task seem underpaid. Set this to be significantly above the total time from start
    to finish that you'd expect a user to take in the worst case.

``base_payment``
    The amount of US dollars to pay for completion of the experiment. The higher this is,
    the easier it will be to attract workers.



Docker Deployment Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``docker_image_base_name``
    A string that will be used to name the docker image generated by this experiment.

    Defaults to the experiment directory name (``bartlett1932``, ``chatroom`` etc).

    To enable repeatability a generated docker image can be pushed to a registry.

    To this end the registry needs to be specified in the ``docker_image_base_name``.
    For example:

        * ``ghcr.io/<GITHUB_USERNAME>/<GITHUB_REPOSITORY>/<EXPERIMENT_NAME>``
        * ``docker.io/<DOCKERHUB_USERNAME>/<EXPERIMENT_NAME>``

``docker_image_name``
    The docker image name to use for this experiment.

    If present, the code in the current directory will not be used when deploying.
    The specified image will be used instead.

    Example: ``ghcr.io/dallinger/dallinger/bartlett1932@sha256:ad3c7b376e23798438c18aae6e0136eb97f5627ddde6baafe1958d40274fa478``

``docker_volumes``
    Additional list of volumes to mount when deploying using docker.

    Example: ``/host/path:/container_path,/another-path:/another-container-path``
