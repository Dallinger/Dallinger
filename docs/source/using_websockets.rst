Using WebSockets in Dallinger Experiments
=========================================

Dallinger provides some helpers to facilitate realtime communication between
participants and the experiment using the WebSocket protocol.

The integration consists of a web API route `GET /chat?channel=<channel>` (see
:doc:`The Web API <web_api>`) to open a WebSocket connection with a
"subscription" to messages on a specific "channel".

Additionally, Experiment classes can implement a
:attr:`~dallinger.experiment.Experiment.channel` attribute which will subscribe
the experiment class to a the named channel. Such experiments should implement a
:func:`~dallinger.experiment.Experiment.receive_message` method to receive and
process any messages on the specified channel as well as the control channel
named `"dallinger_control"`. This function will be called asynchronously by a
worker when the message contains JSON data that includes a ``sender`` or
``participant_id`` property containing the sender's Participant id or a
``node_id`` containing a Node id.

Experiments may also send messages to clients subscribed to a channel using the
:func:`~dallinger.experiment.Experiment.publish_to_subscribers` method.

If you would like your experiment class to receive messages published on
additional WebSocket channels, you will need to subscribe to them in your
Experiment class's :func:`~dallinger.experiment.Experiment.on_launch` method.
For example

::

    def on_launch(self):
        from dallinger.experiment_server.sockets import chat_backend
        chat_backend.subscribe(self, 'my_secondary_channel')
