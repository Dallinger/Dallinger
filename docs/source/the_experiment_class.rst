The Experiment Class
====================

Experiments are designed in Dallinger by creating a custom subclass of the base
Experiment class. The code for the Experiment class is in experiments.py.
Unlike the :doc:`other classes <classes>`, each experiment involves only a
single Experiment object and it is not stored as an entry in a corresponding
table, rather each Experiment is a set of instructions that tell the server
what to do with the database when the server receives requests from outside.

.. module:: dallinger.experiment

.. autoclass:: Experiment

  .. autoinstanceattribute:: verbose
    :annotation:

  .. autoinstanceattribute:: task
    :annotation:

  .. autoinstanceattribute:: session
    :annotation:

  .. autoinstanceattribute:: practice_repeats
    :annotation:

  .. autoinstanceattribute:: experiment_repeats
    :annotation:

  .. autoinstanceattribute:: recruiter
    :annotation:

  .. autoinstanceattribute:: initial_recruitment_size
    :annotation:

  .. autoinstanceattribute:: known_classes
    :annotation:

  .. autoinstanceattribute:: public_properties
    :annotation:

  .. automethod:: __init__

  .. automethod:: add_node_to_network

  .. automethod:: assignment_abandoned

  .. automethod:: assignment_reassigned

  .. automethod:: assignment_returned

  .. automethod:: attention_check

  .. automethod:: attention_check_failed

  .. automethod:: bonus

  .. automethod:: bonus_reason

  .. automethod:: collect

  .. automethod:: create_network

  .. automethod:: create_node

  .. automethod:: load_participant

  .. automethod:: data_check

  .. automethod:: data_check_failed

  .. automethod:: events_for_replay

  .. automethod:: fail_participant

  .. automethod:: get_network_for_participant

  .. automethod:: info_get_request

  .. automethod:: info_post_request

  .. automethod:: is_complete

  .. automethod:: is_overrecruited

  .. automethod:: log

  .. automethod:: log_summary

  .. automethod:: make_uuid

  .. automethod:: networks

  .. automethod:: node_get_request

  .. automethod:: node_post_request

  .. automethod:: recruit

  .. automethod:: replay_event

  .. automethod:: replay_start

  .. automethod:: replay_finish

  .. automethod:: replay_started

  .. automethod:: run

  .. automethod:: save

  .. automethod:: setup

  .. automethod:: submission_successful

  .. automethod:: transformation_get_request

  .. automethod:: transformation_post_request

  .. automethod:: transmission_get_request

  .. automethod:: transmission_post_request

  .. automethod:: vector_get_request

  .. automethod:: vector_post_request
