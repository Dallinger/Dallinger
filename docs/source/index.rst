Dallinger
~~~~~~~~~

Dallinger is a tool to automate experiments that use combinations of automated bots and human subjects recruited on platforms like Mechanical Turk.

Dallinger allows crowd sourced experiments to be abstracted into single function calls that can be inserted into higher-order algorithms. It fully automates the process of recruiting participants, obtaining informed consent, arranging participants into a network, running the experiment, coordinating communication, recording and managing the data, and paying the participants.

The Dallinger technology stack consists of: Python, Redis, Web Sockets, Heroku, AWS, Mechanical Turk, boto, Flask, PostgreSQL, SQLAlchemy, Gunicorn, Pytest and gevent among others.

User Documentation
^^^^^^^^^^^^^^^^^^

These documentation topics are intended to assist people who are attempting
to launch experiments and analyse their data. They cover the basics of installing
and setting up Dallinger, as well as use of the command line tools.

.. toctree::
    :caption: User Documentation
    :maxdepth: 1

    installing_dallinger_for_users
    dallinger_with_anaconda
    aws_etc_keys
    demoing_dallinger
    command_line_utility
    configuration
    email_setup
    python_module
    monitoring_a_live_experiment
    experiment_data
    postico_and_postgres
    running_bots
    registration_on_OSF
    troubleshooting


Experiment Author Documentation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These documentation topics build on the previous set to include help with
designing new experiments for others to use.

.. toctree::
    :caption: Experiment Author Documentation
    :maxdepth: 1

    developing_dallinger_setup_guide
    creating_an_experiment
    docker_setup
    running_the_tests
    the_experiment_class
    classes
    web_api
    communicating_with_the_server
    javascript_api
    rewarding_participants
    waiting_rooms
    writing_bots
    extra_configuration

Core Contribution Documentation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These documentation topics cover setting up a development version of Dallinger,
in order to contribute to the development of Dallinger itself. This is not needed
in order to develop new experiments.

.. toctree::
    :caption: Core Contribution Documentation
    :maxdepth: 1

    developing_dallinger_setup_guide
    running_the_tests
    contributing_to_dallinger

General Information
^^^^^^^^^^^^^^^^^^^

.. toctree::
    :caption: General Information
    :maxdepth: 1

    acknowledgments
    dallinger_the_scientist
