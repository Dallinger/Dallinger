/*globals $, dallinger */
var my_node_id;

// Create the agent.
var create_agent = function () {
  dallinger.createAgent()
    .done(function (resp) {
      my_node_id = resp.node.id;
      console.log(my_node_id);
      $("#stimulus").show();
      $("#response-form").show();
      $("#send-message").removeClass("disabled");
      $("#send-message").html("Send");
      $("#reproduction").focus();
      get_transmissions(my_node_id);
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

var get_transmissions = function (my_node_id) {
  dallinger.getTransmissions(my_node_id, { status: 'pending' })
    .done(function (resp) {
      console.log(resp);
      transmissions = resp.transmissions;
      for (var i = transmissions.length - 1; i >= 0; i--) {
        console.log(transmissions[i]);
        display_info(transmissions[i].info_id);
      }
      setTimeout(function () { get_transmissions(my_node_id); }, 100);
    });
};

var display_info = function(info_id) {
  dallinger.getInfo(my_node_id, info_id)
    .done(function (resp) {
      console.log(resp.info.contents);
      $("#story").append("<p>" + resp.info.contents + "</p>");
    });
};

var send_message = function() {
  $("#send-message").addClass("disabled");
  $("#send-message").html("Sending...");

  response = $("#reproduction").val();
  $("#reproduction").val("");
  $("#story").append("<p style='color: #1693A5;'>" + response + "</p>");
  $("#reproduction").focus();

  dallinger.createInfo(my_node_id, {
    contents: response,
    info_type: "Info"
  }).done(function (resp) {
    console.log("sent!");
    $("#send-message").removeClass("disabled");
    $("#send-message").html("Send");
  });
};

var leave_chatroom = function() {
  dallinger.goToPage("questionnaire");
};

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
