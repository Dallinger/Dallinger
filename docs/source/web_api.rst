Web API
=======

The Dallinger API allows the experiment frontend to communicate with the
backend. Many of these routes correspond to specific functions of
Dallinger's :ref:`classes <classes>`, particularly
:class:`dallinger.models.Node`. For example,
nodes have a ``connect`` method that creates new vectors between nodes
and there is a corresponding ``connect/`` route that allows the frontend
to call this method.

Miscellaneous routes
^^^^^^^^^^^^^^^^^^^^

::

    GET /ad_address/<mode>/<hit_id>

Used to get the address of the experiment on the psiTurk server and to return
participants to Mechanical Turk upon completion of the experiment. This route
is pinged automatically by the function ``submitAssignment`` in dallinger.js.

::

    GET /<directory>/<page>

Returns the html page with the name ``<page>`` from the directory called
``<directory>``.

::

    GET /summary

Returns a summary of the statuses of Participants.

::

    GET /<page>

Returns the html page with the name ``<page>``.

Experiment routes
^^^^^^^^^^^^^^^^^

::

    GET /experiment/<property>

Returns the value of the requested property as a JSON ``<property>``.

::

    GET /info/<node_id>/<info_id>

Returns a JSON description of the requested info as ``info``.
``node_id`` must be specified to ensure the requesting node has access
to the requested info. Calls experiment method
\`info\_get\_request(node, info).

::

    POST /info/<node_id>

Create an info with its origin set to the specified node. *contents*
must be passed as data. ``info_type`` can be passed as data and will
cause the info to be of the specified type. Also calls experiment method
``info_post_request(node, info)``.

::

    POST /launch

Initializes the experiment and opens recruitment. This route is
automatically pinged by Dallinger.

::

    GET /network/<network_id>

Returns a JSON description of the requested network as ``network``.

::

    POST /node/<node_id>/connect/<other_node_id>

Create vector(s) between the ``node`` and ``other_node`` by calling
``node.connect(whom=other_node)``. Direction can be passed as data and
will be forwarded as an argument. Calls experiment method
``vector_post_request(node, vectors)``. Returns a list of JSON
descriptions of the created vectors as ``vectors``.

::

    GET /node/<node_id>/infos

Returns a list of JSON descriptions of the infos created by the node as
``infos``. Infos are identified by calling ``node.infos()``.
``info_type`` can be passed as data and will be forwarded as an
argument. Requesting node and the list of infos are also passed to
experiment method ``info_get_request(node, infos)``.

::

    GET /node/<node_id>/neighbors

Returns a list of JSON descriptions of the node's neighbors as
``nodes``. Neighbors are identified by calling ``node.neighbors()``.
``node_type`` and ``connection`` can be passed as data and will be
forwarded as arguments. Requesting node and list of neighbors are also
passed to experiment method ``node_get_request(node, nodes)``.

::

    GET /node/<node_id>/received_infos

Returns a list of JSON descriptions of the infos sent to the node as
``infos``. Infos are identified by calling ``node.received_infos()``.
``info_type`` can be passed as data and will be forwarded as an
argument. Requesting node and the list of infos are also passed to
experiment method ``info_get_request(node, infos)``.

::

    GET /node/<int:node_id>/transformations

Returns a list of JSON descriptions of all the transformations of a node
identified using ``node.transformations()``. The node id must be
specified in the url. You can also pass ``transformation_type`` as data
and it will be forwarded to ``node.transformations()`` as the argument
``type``.

::

    GET /node/<node_id>/transmissions

Returns a list of JSON descriptions of the transmissions sent to/from
the node as ``transmissions``. Transmissions are identified by calling
``node.transmissions()``. ``direction`` and ``status`` can be passed as
data and will be forwarded as arguments. Requesting node and the list of
transmissions are also passed to experiment method
``transmission_get_request(node, transmissions)``.

::

    POST /node/<node_id>/transmit

Transmit to another node by calling ``node.transmit()``. The sender's
node id must be specified in the url. As with ``node.transmit()`` the
key parameters are ``what`` and ``to_whom`` and they should be passed
as data. However, the values these accept are more limited than for
the backend due to the necessity of serialization.

If ``what`` and ``to_whom`` are not specified they will default to
``None``. Alternatively you can pass an int (e.g. '5') or a class name
(e.g. ``Info`` or ``Agent``). Passing an int will get that info/node,
passing a class name will pass the class. Note that if the class you
are specifying is a custom class it will need to be added to the
dictionary of known\_classes in your experiment code.

You may also pass the values property1, property2, property3,
property4 and property5. If passed this will fill in the relevant
values of the transmissions created with the values you specified.

The transmitting node and a list of created transmissions are sent to
experiment method ``transmission_post_request(node, transmissions)``.
This route returns a list of JSON descriptions of the created
transmissions as ``transmissions``. For example, to transmit all infos
of type Meme to the node with id 10:

::

    reqwest({
        url: "/node/" + my_node_id + "/transmit",
        method: 'post',
        type: 'json',
        data: {
            what: "Meme",
            to_whom: 10,
        },
    });

::

    GET /node/<node_id>/vectors

Returns a list of JSON descriptions of vectors connected to the node as
``vectors``. Vectors are identified by calling ``node.vectors()``.
``direction`` and ``failed`` can be passed as data and will be forwarded
as arguments. Requesting node and list of vectors are also passed to
experiment method ``vector_get_request(node, vectors)``.

::

    POST /node/<participant_id>

Create a node for the specified participant. The route calls the
following experiment methods:
``get_network_for_participant(participant)``,
``create_node(network, participant)``,
``add_node_to_network(node, network)``, and
``node_post_request(participant, node)``. Returns a JSON description of
the created node as ``node``.

::

    POST /notifications
    GET /notifications

This is the route to which notifications from AWS are sent. It is also
possible to send your own notifications to this route, thereby
simulating notifications from AWS. Necessary arguments are
``Event.1.EventType``, which can be ``AssignmentAccepted``,
``AssignmentAbandoned``, ``AssignmentReturned`` or
``AssignmentSubmitted``, and ``Event.1.AssignmentId``, which is the id
of the relevant assignment. In addition, Dallinger uses a custom event
type of ``NotificationMissing``.

::

    GET /participant/<participant_id>

Returns a JSON description of the requested participant as
``participant``.

::

    POST /participant/<worker_id>/<hit_id>/<assignment_id>/<mode>

Create a participant. Returns a JSON description of the participant as
``participant``.

::

    POST /question/<participant_id>

Create a question. ``question``, ``response`` and ``question_id`` should
be passed as data. Does not return anything.

::

    POST /transformation/<int:node_id>/<int:info_in_id>/<int:info_out_id>

Create a transformation from ``info_in`` to ``info_out`` at the
specified node. ``transformation_type`` can be passed as data and the
transformation will be of that class if it is a known class. Returns a
JSON description of the created transformation.
