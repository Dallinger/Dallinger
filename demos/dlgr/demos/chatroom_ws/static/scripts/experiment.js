/*globals $, dallinger */
var my_node_id;
var chatroom_socket;


// Create the agent.
var create_agent = function() {
  $('#participant-number').text(dallinger.identity.participantId);
  var spinner = dallinger.BusyForm();
  spinner.freeze([$('#reproduction')], [$('#send-message, #leave-chat')]);
  dallinger.createAgent()
    .done(function (resp) {
      my_node_id = resp.node.id;
      console.log(my_node_id);
      spinner.unfreeze();
      $("#reproduction").focus();
      open_chatroom();
    })
    .fail(function (rejection) {
      // A 403 is our signal that it's time to go to the questionnaire
      if (rejection.status === 403) {
        dallinger.allowExit();
        dallinger.goToPage('questionnaire');
      } else {
        dallinger.error(rejection);
      }
    });
};

var open_chatroom = function () {
  var ws_scheme = (window.location.protocol === "https:") ? 'wss://' : 'ws://';
  // Setup a websocket connection to the "chatroom", passing our worker_id and participant_id
  chatroom_socket = new ReconnectingWebSocket(
    ws_scheme + location.host + "/chat?channel=chatroom&worker_id=" + dallinger.identity.workerId + '&participant_id=' + dallinger.identity.participantId
  );
  chatroom_socket.onopen(function () {
    chatroom_socket.send('chatroom:' + JSON.stringify({
      'type': 'log',
      'content': dallinger.identity.participantId + ' has joined the chat.',
      'sender': dallinger.identity.participantId,
      'node': my_node_id,
    }));
  });
  chatroom_socket.onmessage = function (msg) {
    // Ignore messages not from the chatroom
    if (msg.data.indexOf('chatroom:') !== 0) { return; }
    var data = JSON.parse(msg.data.substring(9));
    var type = data.type;
    var content = data.content;
    var sender = data.sender;
    if (type == 'message') {
      add_message(content, sender);
    } else if (type == 'log') {
      add_log(content);
      if (data.action == 'finish') {
        $("#send-message, #reproduction").prop('disabled', true);
      }
    }
  };
  return chatroom_socket;
};

var add_message = function(content, sender) {
  $("#story").append("<p><strong>Participant " + sender + ":</strong> " + content + "</p>");
};

var send_message = function() {
  response = $("#reproduction").val();
  chatroom_socket.send('chatroom:' + JSON.stringify({
    'type': 'message',
    'content': response,
    'sender': dallinger.identity.participantId,
    'node': my_node_id,
  }));
  response = $("#reproduction").val('');
};

var leave_chatroom = function() {
  chatroom_socket.send('chatroom:' + JSON.stringify({
    'type': 'log',
    'content': 'Participant ' + dallinger.identity.participantId + ' has left the chat.',
    'sender': dallinger.identity.participantId,
    'node': my_node_id,
  }));
  chatroom_socket.onclose = function () {
    dallinger.goToPage("questionnaire");
  };
  try {
    chatroom_socket.close();
  } catch(err) {
    dallinger.goToPage("questionnaire");
  }
};

var add_log = function (content) {
  var $log = $("#log");
  $log.append("<p>" + content + "</p>");
  $log.scrollTop($log.height());
}

$(document).keypress(function (e) {
  if (e.which === 13) {
    console.log("enter!");
    $("#send-message").click();
    return false;
  }
});

$(document).ready(function() {

  // Send a message.
  $("#send-message").click(function() {
    send_message();
  });

  // Leave the chatroom.
  $("#leave-chat").click(function() {
    leave_chatroom();
  });

  // Proceed to the waiting room.
  $("#go-to-waiting-room").click(function() {
      dallinger.goToPage("waiting");
  });

});
