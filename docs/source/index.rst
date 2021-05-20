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

Beginner Documentation
^^^^^^^^^^^^^^^^^^^^^^

Many Dallinger users may not have lots of programming experience, and might
want a bit more information about the inner workings of Dallinger in a
beginner-friendly format. Thomas Morgan has started such a project:
"Dallinger for Programming Novices". Every Dallinger user is encouraged to take a look at this guide, which is a
nice complement to the documentation presented here.

.. toctree::
    :caption: Beginner Documentation
    :maxdepth: 1

    Dallinger for Programming Novices <https://github.com/thomasmorgan/dallinger-for-novices>

Dallinger Demos
^^^^^^^^^^^^^^^

Several demos demonstrate Dallinger in action:

.. toctree::
    :caption: Dallinger Demos
    :maxdepth: 1

    demo_index


Experiment Author Documentation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

These documentation topics build on the previous set to include help with
designing new experiments for others to use.

.. toctree::
    :caption: Experiment Author Documentation
    :maxdepth: 1

    developing_dallinger_setup_guide
    creating_an_experiment
    networks
    docker_support
    the_experiment_class
    classes
    web_api
    communicating_with_the_server
    javascript_api
    rewarding_participants
    waiting_rooms
    writing_bots
    extra_configuration
    recruitment
    scheduled_tasks
    private_repo

Core Contribution Documentation
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This section covers extra topics relevant to those wishing to contribute to the development of Dallinger itself. This is not needed
in order to develop new experiments. Follow the Developer Installation process from the previous section to get started.

.. toctree::
    :caption: Core Contribution Documentation
    :maxdepth: 1

    running_the_tests
    building_documentation
    contributing_to_dallinger

General Information
^^^^^^^^^^^^^^^^^^^

.. toctree::
    :caption: General Information
    :maxdepth: 1

    acknowledgments
    dallinger_the_scientist
