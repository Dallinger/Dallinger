Database API
============

The classes involved in a Wallace experiment are:
:class:`~wallace.models.Network`, :class:`~wallace.models.Node`,
:class:`~wallace.models.Vector`, :class:`~wallace.models.Info`,
:class:`~wallace.models.Transmission`,
:class:`~wallace.models.Transformation`,
:class:`~wallace.models.Participant`, and
:class:`~wallace.models.Question`. The code for all these classes can
be seen in ``models.py``. Each class has a corresponding table in the
database, with each instance stored as a row in the table. Accordingly,
each class is defined, in part, by the columns that constitute the table
it is stored in. In addition, the classes have relationships to other
objects and a number of functions.

The classes have relationships to each other as shown in the diagram
below. Be careful to note which way the arrows point. A :class:`~wallace.models.Node` is a
point in a :class:`~wallace.models.Network` that might be associated with a :class:`~wallace.models.Participant`.
A :class:`~wallace.models.Vector` is a directional connection between a :class:`~wallace.models.Node` and another
:class:`~wallace.models.Node`. An :class:`~wallace.models.Info` is information created by a :class:`~wallace.models.Node`. A
:class:`~wallace.models.Transmission` is an instance of an :class:`~wallace.models.Info` being sent along a
:class:`~wallace.models.Vector`. A :class:`~wallace.models.Transformation` is a relationship between an :class:`~wallace.models.Info`
and another :class:`~wallace.models.Info`. A :class:`~wallace.models.Question` is a survey response created by a
:class:`~wallace.models.Participant`.

.. figure:: _static/class_chart.jpg
   :alt: 

SharedMixin
-----------

All Wallace classes inherit from a ``SharedMixin`` which provides multiple
columns that are common across tables:

.. autoattribute:: wallace.models.SharedMixin.id
    :annotation:

.. autoattribute:: wallace.models.SharedMixin.creation_time
    :annotation:

.. autoattribute:: wallace.models.SharedMixin.property1
    :annotation:

.. autoattribute:: wallace.models.SharedMixin.property2
    :annotation:

.. autoattribute:: wallace.models.SharedMixin.property3
    :annotation:

.. autoattribute:: wallace.models.SharedMixin.property4
    :annotation:

.. autoattribute:: wallace.models.SharedMixin.property5
    :annotation:

.. autoattribute:: wallace.models.SharedMixin.failed
    :annotation:

.. autoattribute:: wallace.models.SharedMixin.time_of_death
    :annotation:

Network
-------

The :class:`~wallace.models.Network` object can be imagined as a set of other objects with
some functions that perform operations over those objects. The objects
that :class:`~wallace.models.Network`'s have direct access to are all the :class:`~wallace.models.Node`'s in the
network, the :class:`~wallace.models.Vector`'s between those Nodes, Infos created by those
Nodes, Transmissions sent along the Vectors by those Nodes and
Transformations of those Infos. Participants and Questions do not exist
within Networks. An experiment may involve multiple Networks,
Transmissions can only occur within networks, not between them.

.. autoclass:: wallace.models.Network

Columns
~~~~~~~

.. autoattribute:: wallace.models.Network.type
    :annotation:

.. autoattribute:: wallace.models.Network.max_size
    :annotation:

.. autoattribute:: wallace.models.Network.full
    :annotation:

.. autoattribute:: wallace.models.Network.role
    :annotation:

Relationships
~~~~~~~~~~~~~

.. attribute:: wallace.models.Network.all_nodes

    All the Nodes in the network.

.. attribute:: wallace.models.Network.all_vectors

    All the vectors in the network.

.. attribute:: wallace.models.Network.all_infos

    All the infos in the network.

.. attribute:: wallace.models.Network.networks_transmissions

    All the transmissions int he network.

.. attribute:: wallace.models.Network.networks_transformations

    All the transformations in the network.

Methods
~~~~~~~

.. automethod:: wallace.models.Network.__repr__

.. automethod:: wallace.models.Network.__json__

.. automethod:: wallace.models.Network.calculate_full

.. automethod:: wallace.models.Network.fail

.. automethod:: wallace.models.Network.infos

.. automethod:: wallace.models.Network.latest_transmission_recipient

.. automethod:: wallace.models.Network.nodes

.. automethod:: wallace.models.Network.print_verbose

.. automethod:: wallace.models.Network.size

.. automethod:: wallace.models.Network.transformations

.. automethod:: wallace.models.Network.transmissions

.. automethod:: wallace.models.Network.vectors

Node
----

Each Node represents a single point in a single network. A Node must be
within a Network and may also be associated with a Participant.

.. autoclass:: wallace.models.Node

Columns
~~~~~~~

.. autoattribute:: wallace.models.Node.type
    :annotation:

.. autoattribute:: wallace.models.Node.network_id
    :annotation:

.. autoattribute:: wallace.models.Node.participant_id
    :annotation:

Relationships
~~~~~~~~~~~~~

.. autoattribute:: wallace.models.Node.network
    :annotation:

.. autoattribute:: wallace.models.Node.participant
    :annotation:

.. attribute:: wallace.models.Node.all_outgoing_vectors

    All the vectors going out from this Node.

.. attribute:: wallace.models.Node.all_incoming_vectors

    All the vectors coming in to this Node.

.. attribute:: wallace.models.Node.all_infos

    All Infos created by this Node.

.. attribute:: wallace.models.Node.all_outgoing_transmissions

    All Transmissions sent from this Node.

.. attribute:: wallace.models.Node.all_incoming_transmissions

    All Transmissions sent to this Node.

.. attribute:: wallace.models.Node.transformations_here

    All transformations that took place at this Node.

Methods
~~~~~~~

.. automethod:: wallace.models.Node.__repr__

.. automethod:: wallace.models.Node.__json__

.. automethod:: wallace.models.Node._to_whom

.. automethod:: wallace.models.Node._what

.. automethod:: wallace.models.Node.connect

.. automethod:: wallace.models.Node.fail

.. automethod:: wallace.models.Node.is_connected

.. automethod:: wallace.models.Node.infos

.. automethod:: wallace.models.Node.mutate

.. automethod:: wallace.models.Node.neighbors

.. automethod:: wallace.models.Node.receive

.. automethod:: wallace.models.Node.received_infos

.. automethod:: wallace.models.Node.replicate

.. automethod:: wallace.models.Node.transformations

.. automethod:: wallace.models.Node.transmissions

.. automethod:: wallace.models.Node.transmit

.. automethod:: wallace.models.Node.update

.. automethod:: wallace.models.Node.vectors


Vector
------

A vector is a directional link between two nodes. Nodes connected by a
vector can send Transmissions to each other, but because Vectors have a
direction, two Vectors are needed for bi-directional Transmissions.

.. autoclass:: wallace.models.Vector

Columns
~~~~~~~

.. autoattribute:: wallace.models.Vector.origin_id
    :annotation:

.. autoattribute:: wallace.models.Vector.destination_id
    :annotation:

.. autoattribute:: wallace.models.Vector.network_id
    :annotation:

Relationships
~~~~~~~~~~~~~

.. autoattribute:: wallace.models.Vector.origin
    :annotation:

.. autoattribute:: wallace.models.Vector.destination
    :annotation:

.. autoattribute:: wallace.models.Vector.network
    :annotation:

.. attribute:: wallace.models.Vector.all_transmissions

    All Transmissions sent along the Vector.


Methods
~~~~~~~

.. automethod:: wallace.models.Vector.__repr__

.. automethod:: wallace.models.Vector.__json__

.. automethod:: wallace.models.Vector.fail

.. automethod:: wallace.models.Vector.transmissions

Info
----

An Info is a piece of information created by a Node. It can be sent
along Vectors as part of a Transmission.

.. autoclass:: wallace.models.Info

Columns
~~~~~~~

.. autoattribute:: wallace.models.Info.id
    :annotation:

.. autoattribute:: wallace.models.Info.creation_time
    :annotation:

.. autoattribute:: wallace.models.Info.property1
    :annotation:

.. autoattribute:: wallace.models.Info.property2
    :annotation:

.. autoattribute:: wallace.models.Info.property3
    :annotation:

.. autoattribute:: wallace.models.Info.property4
    :annotation:

.. autoattribute:: wallace.models.Info.property5
    :annotation:

.. autoattribute:: wallace.models.Info.failed
    :annotation:

.. autoattribute:: wallace.models.Info.time_of_death
    :annotation:

.. autoattribute:: wallace.models.Info.type
    :annotation:

.. autoattribute:: wallace.models.Info.origin_id
    :annotation:

.. autoattribute:: wallace.models.Info.network_id
    :annotation:

.. autoattribute:: wallace.models.Info.contents
    :annotation:

Relationships
~~~~~~~~~~~~~

.. autoattribute:: wallace.models.Info.origin
    :annotation:

.. autoattribute:: wallace.models.Info.network
    :annotation:

.. attribute:: wallace.models.Info.all_transmissions

    All Transmissions of this Info.

.. attribute:: wallace.models.Info.transformation_applied_to

    All Transformations of which this info is the ``info_in``

.. attribute:: wallace.models.Info.transformation_whence

    All Transformations of which this info is the ``info_out``

Methods
~~~~~~~

.. automethod:: wallace.models.Info.__repr__

.. automethod:: wallace.models.Info.__json__

.. automethod:: wallace.models.Info._mutated_contents

.. automethod:: wallace.models.Info.fail

.. automethod:: wallace.models.Info.transformations

.. automethod:: wallace.models.Info.transmissions

Transmission
------------

A transmission represents an instance of an Info being sent along a
Vector. Transmissions are not necessarily received when they are sent
(like an email) and must also be received by the Node they are sent to.

.. autoclass:: wallace.models.Transmission

Columns
~~~~~~~

.. autoattribute:: wallace.models.Transmission.origin_id
    :annotation:

.. autoattribute:: wallace.models.Transmission.destination_id
    :annotation:

.. autoattribute:: wallace.models.Transmission.vector_id
    :annotation:

.. autoattribute:: wallace.models.Transmission.network_id
    :annotation:

.. autoattribute:: wallace.models.Transmission.info_id
    :annotation:

.. autoattribute:: wallace.models.Transmission.receive_time
    :annotation:

.. autoattribute:: wallace.models.Transmission.status
    :annotation:

Relationships
~~~~~~~~~~~~~

.. autoattribute:: wallace.models.Transmission.origin
    :annotation:

.. autoattribute:: wallace.models.Transmission.destination
    :annotation:

.. autoattribute:: wallace.models.Transmission.vector
    :annotation:

.. autoattribute:: wallace.models.Transmission.network
    :annotation:

.. autoattribute:: wallace.models.Transmission.info
    :annotation:

Methods
~~~~~~~

.. automethod:: wallace.models.Transmission.__repr__

.. automethod:: wallace.models.Transmission.__json__

.. automethod:: wallace.models.Transmission.fail

.. automethod:: wallace.models.Transmission.mark_received


Transformation
--------------

A Transformation is a relationship between two Infos. It is similar to
how a Vector indicates a relationship between two Nodes, but whereas a
Vector allows Nodes to Transmit to each other, Transformations don't
allow Infos to do anything new. Instead they are a form of book-keeping
allowing you to keep track of relationships between various Infos.

.. autoclass:: wallace.models.Transformation

Columns
~~~~~~~

.. autoattribute:: wallace.models.Transformation.type
    :annotation:

.. autoattribute:: wallace.models.Transformation.node_id
    :annotation:

.. autoattribute:: wallace.models.Transformation.network_id
    :annotation:

.. autoattribute:: wallace.models.Transformation.info_in_id
    :annotation:

.. autoattribute:: wallace.models.Transformation.info_out_id
    :annotation:

Relationships
~~~~~~~~~~~~~

.. autoattribute:: wallace.models.Transformation.node
    :annotation:

.. autoattribute:: wallace.models.Transformation.network
    :annotation:

.. autoattribute:: wallace.models.Transformation.info_in
    :annotation:

.. autoattribute:: wallace.models.Transformation.info_out
    :annotation:

Methods
~~~~~~~

.. automethod:: wallace.models.Transformation.__repr__

.. automethod:: wallace.models.Transformation.__json__

.. automethod:: wallace.models.Transformation.fail


Participant
-----------

The Participant object corresponds to a real world participant. Each
person who takes part will have a corresponding entry in the Participant
table. Participants can be associated with Nodes and Questions.

.. autoclass:: wallace.models.Participant

Columns
~~~~~~~

.. autoattribute:: wallace.models.Participant.type
    :annotation:

.. autoattribute:: wallace.models.Participant.worker_id
    :annotation:

.. autoattribute:: wallace.models.Participant.assignment_id
    :annotation:

.. autoattribute:: wallace.models.Participant.unique_id
    :annotation:

.. autoattribute:: wallace.models.Participant.hit_id
    :annotation:

.. autoattribute:: wallace.models.Participant.mode
    :annotation:

.. autoattribute:: wallace.models.Participant.end_time
    :annotation:

.. autoattribute:: wallace.models.Participant.base_pay
    :annotation:

.. autoattribute:: wallace.models.Participant.bonus
    :annotation:

.. autoattribute:: wallace.models.Participant.status
    :annotation:

Relationships
~~~~~~~~~~~~~

.. attribute:: wallace.models.Participant.all_questions

    All the questions associated with this participant.

.. attribute:: wallace.models.Participant.all_nodes

    All the Nodes associated with this participant.

Methods
~~~~~~~

.. automethod:: wallace.models.Participant.__json__

.. automethod:: wallace.models.Participant.fail

.. automethod:: wallace.models.Participant.infos

.. automethod:: wallace.models.Participant.nodes

.. automethod:: wallace.models.Participant.questions

Question
--------

A Question is a way to store information associated with a Participant
as opposed to a Node (Infos are made by Nodes, not Participants).
Questions are generally useful for storing responses debriefing
questions etc.

.. autoclass:: wallace.models.Question

Columns
~~~~~~~

.. autoattribute:: wallace.models.Question.type
    :annotation:

.. autoattribute:: wallace.models.Question.participant_id
    :annotation:

.. autoattribute:: wallace.models.Question.number
    :annotation:

.. autoattribute:: wallace.models.Question.question
    :annotation:

.. autoattribute:: wallace.models.Question.response
    :annotation:

Relationships
~~~~~~~~~~~~~

.. autoattribute:: wallace.models.Question.participant

Methods
~~~~~~~

.. automethod:: wallace.models.Question.__json__

.. automethod:: wallace.models.Question.fail

