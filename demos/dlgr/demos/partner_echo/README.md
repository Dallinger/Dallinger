# Partner echo

Two participants are paired. Each message one of them sends is delivered to the
other, and the sender is told which participant it was forwarded to.

Each browser opens an `/experiment-socket` connection with no channel subscription.
An incoming message runs `handle_websocket_message` directly on the web process
holding the socket, rather than travelling through Redis first. The experiment
responds via `publish_to_participants`, which addresses the partner by participant
ID rather than broadcasting to a channel they both watch.

The acknowledgment to the sender is addressed to the sender's participant ID *and*
to the specific page load that sent the message. `dallinger.openExperimentSocket()`
tags each connection with `dallinger.pageScope`, a random value generated once when
the page loads. The server passes that value to the experiment with every message
the socket sends, and the experiment echoes it back as the `scope` of the
acknowledgment — so only the tab that sent the message receives it. A stale tab
from an earlier attempt has a different `pageScope` and is skipped. The message to
the partner carries no scope, so it reaches every tab the partner has open.
