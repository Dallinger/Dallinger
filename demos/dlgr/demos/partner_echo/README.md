# Partner echo

Two participants are paired. Whatever one of them sends is delivered to the
other, and the sender is told which participant it was forwarded to.

The demo is the smallest thing that exercises the two websocket features
Dallinger added for low-latency experiments. Each browser opens an
`/experiment-socket` connection with `dallinger.openExperimentSocket()` and
subscribes to no channel at all, so an incoming message runs
`handle_websocket_message` on the web process holding the socket rather than
travelling through redis to a worker. The experiment then answers with
`publish_to_participants`, which addresses the partner by participant id
instead of broadcasting to a channel both of them watch, and the browser
receives the answer through the socket's `onDirect` callback.

The acknowledgment to the sender carries the connection's `scope`, so it
reaches only the page that sent the message. A socket opened with
`dallinger.openExperimentSocket()` sends a scope identifying the page load
unless it is given another. The message to the partner carries no scope, so it
reaches every connection they hold.
