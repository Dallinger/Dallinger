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
  // Subscribe to the "chatroom" channel
  chatroom_socket = dallinger.openChatSocket({channel: 'chatroom'});
  chatroom_socket.onOpen(function (event) {
    // Announce ourselves once, not again after a reconnect
    if (event.isReconnect) { return; }
    chatroom_socket.send('chatroom', {
      'type': 'log',
      'content': 'Participant ' + dallinger.identity.participantId + ' has joined the chat.',
      'sender': dallinger.identity.participantId,
      'node_id': my_node_id,
    });
  });
  chatroom_socket.onBroadcast(function (data) {
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
  });
  return chatroom_socket;
};

var add_message = function(content, sender) {
  $("#story").append(
    $("<p>").append($("<strong>").text("Participant " + sender + ": ")).append($("<span>").text(content))
  );
};

var send_message = function() {
  var response = $("#reproduction").val();
  chatroom_socket.send('chatroom', {
    'type': 'message',
    'content': response,
    'sender': dallinger.identity.participantId,
    'node_id': my_node_id,
  });
  $("#reproduction").val('');
};

var leave_chatroom = function() {
  chatroom_socket.send('chatroom', {
    'type': 'log',
    'content': 'Participant ' + dallinger.identity.participantId + ' has left the chat.',
    'sender': dallinger.identity.participantId,
    'node_id': my_node_id,
  });
  // Let the goodbye reach the server before leaving. If the connection is
  // down, close() drops it rather than make the participant wait.
  chatroom_socket.close().always(function () {
    dallinger.goToPage("questionnaire");
  });
};

var add_log = function (content) {
  var $log = $("#log");
  $log.append($("<p>").text(content));
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
