var my_node_id;

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
    window.location.href = '/waiting?hit_id=' + dallinger.identity.hitId + '&assignment_id=' + dallinger.identity.assignmentId + '&worker_id=' + dallinger.identity.workerId + '&mode=' + dallinger.identity.mode;
  });

});


// Create the agent.
create_agent = function () {
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
    .fail(function () {
      dallinger.goToPage("questionnaire");
    });
};

get_transmissions = function (my_node_id) {
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

display_info = function(info_id) {
  dallinger.getInfo(my_node_id, info_id)
    .done(function (resp) {
      console.log(resp.info.contents);
      $("#story").append("<p>" + resp.info.contents + "</p>");
    });
};

send_message = function() {
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

leave_chatroom = function() {
  dallinger.goToPage("questionnaire");
};

$(document).keypress(function (e) {
  if (e.which === 13) {
    console.log("enter!");
    $("#send-message").click();
    return false;
  }
});
