/*globals $, dallinger */
var echo_socket;

var create_agent = function () {
  $('#participant-number').text(dallinger.identity.participantId);
  var spinner = dallinger.BusyForm();
  spinner.freeze([$('#reproduction')], [$('#send-message, #leave-experiment')]);
  dallinger.createAgent()
    .done(function () {
      spinner.unfreeze();
      $("#reproduction").focus();
      open_socket();
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

var open_socket = function () {
  // No channel: this connection sends messages to the experiment, and
  // receives only the ones addressed to this participant.
  echo_socket = dallinger.openExperimentSocket();
  echo_socket.onDirect(function (data) {
    if (data.type === 'message') {
      add_message(data.content, data.sender);
    } else if (data.type === 'forwarded') {
      add_log(data.to.length ? "Forwarded to participant " + data.to.join(", ") + "." : "Nobody to forward to yet.");
    }
  });
  echo_socket.onRefused(function (code, reason) {
    add_log("The server refused the connection: " + reason);
  });
  return echo_socket;
};

var send_message = function () {
  var response = $("#reproduction").val();
  echo_socket.send('partner_echo', {
    'type': 'message',
    'content': response
  });
  add_message(response, dallinger.identity.participantId);
  $("#reproduction").val('');
};

var leave_experiment = function () {
  echo_socket.close().always(function () {
    dallinger.goToPage("questionnaire");
  });
};

var add_message = function (content, sender) {
  $("#story").append(
    $("<p>").append($("<strong>").text("Participant " + sender + ": ")).append($("<span>").text(content))
  );
};

var add_log = function (content) {
  var $log = $("#log");
  $log.append($("<p>").text(content));
  $log.scrollTop($log.height());
};

$(document).keypress(function (e) {
  if (e.which === 13) {
    $("#send-message").click();
    return false;
  }
});

$(document).ready(function () {
  $("#send-message").click(function () {
    send_message();
  });

  $("#leave-experiment").click(function () {
    leave_experiment();
  });

  $("#go-to-waiting-room").click(function () {
    dallinger.goToPage("waiting");
  });
});
