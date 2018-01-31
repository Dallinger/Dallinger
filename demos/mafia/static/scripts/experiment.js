var currentNodeId;
var currentNodeName;
var currentNodeType;
var wasDaytime = 'False';
var switches = 0;
var voted = false;

$(document).ready(function() {
  // Print the consent form.
  $("#print-consent").click(function() {
    window.print();
  });

  // Consent to the experiment.
  $("#consent").click(function() {
    store.set("hit_id", dallinger.getUrlParameter("hit_id"));
    store.set("worker_id", dallinger.getUrlParameter("worker_id"));
    store.set("assignment_id", dallinger.getUrlParameter("assignment_id"));
    store.set("mode", dallinger.getUrlParameter("mode"));

    window.location.href = '/instructions';
  });

  // Consent to the experiment.
  $("#no-consent").click(function() {
    self.close();
  });

  // Proceed to the waiting room.
  $("#go-to-waiting-room").click(function() {
    allow_exit();
    window.location.href = "/waiting";
  });

  // Send a message.
  $("#send-message").click(function() {
    send_message();
  });

  // Vote.
  $("#vote").click(function() {
    vote();
  });

  // Leave the chatroom.
  $("#leave-chat").click(function() {
    leave_chatroom();
  });

  // Submit the questionnaire.
  $("#submit-questionnaire").click(function() {
    if (participant_id > 0) {
      submitResponses();
    }
    submitAssignment();
  });
});

// Create the agent.
create_agent = function() {
  reqwest({
    url: "/node/" + participant_id,
    method: "post",
    type: "json",
    success: function(resp) {
      currentNodeId = resp.node.id;
      currentNodeName = resp.node.property1;
      currentNodeType = resp.node.type;
      $("#narrator").html("The game will begin shortly...");
      $("#stimulus").show();
      setTimeout(function () { $("#stimulus").hide(); showExperiment(); }, 1000);
    },
    error: function(err) {
      console.log(err);
      errorResponse = JSON.parse(err.response);
      if (errorResponse.hasOwnProperty("html")) {
        $("body").html(errorResponse.html);
      } else {
        allow_exit();
        go_to_page("questionnaire");
      }
    }
  });
};

getParticipants = function() {
  reqwest({
    url: "/live_participants/" + currentNodeId + '/' + 1,
    method: 'get',
    type: "json",
    success: function (resp) {
      var participantList = resp.participants;
      showParticipants(participantList, "#participants", 'option');
    },
    error: function (err) {
        console.log(err);
    }
  });
};

getMafia = function() {
  reqwest({
    url: "/live_participants/" + currentNodeId + '/' + 0,
    method: 'get',
    type: "json",
    success: function (resp) {
      var mafiaList = resp.participants;
      showParticipants(mafiaList, "#mafiosi", 'li');
    },
    error: function (err) {
        console.log(err);
    }
  });
}

showParticipants = function(participantList, tag, subtag) {
  $(tag).html('')
  if (tag == "#mafiosi") {
    $(tag).append('<h4>List of Living Mafia</h4>')
  }
  for (i = 0; i < participantList.length; i++) {
    // Add the next participant.
    var name = participantList[i];
    $(tag).append('<' + subtag + '>' + name + '</' + subtag + '>');
  }
};

showExperiment = function() {
  // submitResponses();
  getParticipants();
  $('#name').html('You are a ' + currentNodeType + "! Your player's name is: " + currentNodeName)
  $("#player").show();
  $("#clock").show();
  $("#response-form").show();
  $("#send-message").removeClass("disabled");
  $("#send-message").html("Send");
  $("#reproduction").focus();
  $("#vote-form").show();
  if (currentNodeType == 'mafioso') {
    getMafia();
    $("#mafia").show();
  }
  get_transmissions();
};

check_phase = function() {
    reqwest({
        url: "/phase/" + currentNodeId + '/' + switches + '/' + wasDaytime,
        method: 'get',
        success: function (resp) {
            if (resp.daytime == 'True') {
              $('#remaining').html('Time remaining this day: ' + resp.time)
            } else {
              $('#remaining').html('Time remaining this night: ' + resp.time)
            }
            if (resp.winner) {
              $("#player").hide();
              $("#clock").hide();
              $("#response-form").hide();
              $("#vote-form").hide();
              if (currentNodeType == 'mafioso') {
                $("#mafia").hide();
              }
              $("#narrator").html(resp.victim[0] + ", who is a " + resp.victim[1] + ", has been eliminated! Congratulations, the " + resp.winner + " have won!");
              $("#stimulus").show();
              setTimeout(function () { leave_chatroom(); }, 10000);
            } else if (wasDaytime != resp.daytime) {
              voted = false;
              if (resp.daytime == 'False') {
                document.body.style.backgroundColor = "royalblue";
                $("#narrator").html(resp.victim[0] + ", who is a " + resp.victim[1] + ", has been eliminated!");
              } else {
                document.body.style.backgroundColor = "lightskyblue";
                $("#narrator").html(resp.victim[0] + " has been eliminated!");
              }
              $("#stimulus").show();
              wasDaytime = resp.daytime;
              switches++;
              if (resp.victim[0] == currentNodeName) {
                setTimeout(function () { leave_chatroom(); }, 3000);
              }
              getParticipants();
              if (currentNodeType == 'mafioso' && resp.victim[1] == 'mafioso') {
                getMafia();
              }
              setTimeout(function () { $("#stimulus").hide(); get_transmissions(currentNodeId); }, 3000);
            } else {
              setTimeout(function () { $("#stimulus").hide(); get_transmissions(currentNodeId); }, 100);
            }
        },
        error: function (err) {
            console.log(err);
            setTimeout(function () { get_transmissions(currentNodeId); }, 100);
        }
    });
};

get_transmissions = function() {
  reqwest({
    url: "/node/" + currentNodeId + "/transmissions",
    method: "get",
    type: "json",
    data: { status: "pending" },
    success: function(resp) {
      transmissions = resp.transmissions;
      for (var i = transmissions.length - 1; i >= 0; i--) {
        displayInfo(transmissions[i].info_id);
      }
      check_phase();
    },
    error: function (err) {
      console.log(err);
      errorResponse = JSON.parse(err.response);
      $("body").html(errorResponse.html);
    }
  });
};

displayInfo = function(infoId) {
  reqwest({
    url: "/info/" + currentNodeId + "/" + infoId,
    method: "get",
    type: "json",
    success: function(resp) {
      var word = resp.info.contents;
      if (resp.info.type == 'text') {
        $("#reply").append("<p>" + word + "</p>");
      } else {
        $("#votes").append("<p>" + word + "</p>");
      }
    },
    error: function (err) {
      errorResponse = JSON.parse(err.response);
      $("body").html(errorResponse.html);
    }
  });
};

send_message = function() {
  if (currentNodeType == 'bystander' && wasDaytime == 'False') {
    return;
  }
  response = $("#reproduction").val();
  // typing box
  // don't let people submit an empty response
  if (response.length === 0) {
    return;
  }
  response = currentNodeName + ': ' + $("#reproduction").val();

  $(
    "#reply"
  ).append("<p style='color: chocolate;'>" + response + "</p>");

  $("#reproduction").val("");
  $("#reproduction").focus();

  reqwest({
    url: "/info/" + currentNodeId,
    method: "post",
    data: { contents: response, info_type: "Text" },
    success: function(resp) {
      $("#send-message").removeClass("disabled");
      $("#send-message").html("Send");
    }
  });
};

vote = function() {
  if (currentNodeType == 'bystander' && wasDaytime == 'False' || voted) {
    return;
  }
  voted = true;
  response = currentNodeName + ': ' + $("#participants").val();
  $(
    "#votes"
  ).append("<p style='color: chocolate;'>" + response + "</p>");

  reqwest({
    url: "/info/" + currentNodeId,
    method: "post",
    data: { contents: response, info_type: "Vote" },
    success: function(resp) {
      $("#vote").removeClass("disabled");
      $("#vote").html("Vote");
    }
  });
};

leave_chatroom = function() {
  allow_exit();
  go_to_page("questionnaire");
};

$(document).keypress(function(e) {
  if (e.which == 13) {
    $("#send-message").click();
    return false;
  }
});

// hack for Dallinger 2.0/3.0
submitResponses = function() {
  submitNextResponse(0);
};
