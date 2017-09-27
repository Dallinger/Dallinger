var uniqueWords = [];
var currentNodeId;

$(document).ready(function() {
  // Print the consent form.
  $("#print-consent").click(function() {
    window.print();
  });

  // Consent to the experiment.
  $("#consent").click(function() {
    store.set("hit_id", getUrlParameter("hit_id"));
    store.set("worker_id", getUrlParameter("worker_id"));
    store.set("assignment_id", getUrlParameter("assignment_id"));
    store.set("mode", getUrlParameter("mode"));

    allow_exit();
    window.location.href = '/instructions';
  });

  // Do not consent to the experiment.
  $("#no-consent").click(function() {
    allow_exit();
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
      getWordList();
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

getWordList = function() {
  reqwest({
    url: "/node/" + currentNodeId + "/received_infos",
    method: "get",
    type: "json",
    success: function(resp) {
      var wordList = JSON.parse(resp.infos[0].contents);
      showWordList(wordList);
    },
    error: function(err) {
      console.log(err);
      errorResponse = JSON.parse(err.response);
      $("body").html(errorResponse.html);
    }
  });
};

showWordList = function(wl) {
  if (wl.length === 0) {
    // Show filler task.
    showFillerTask();
  } else {
    // Show the next word.
    $("#wordlist").html(wl.pop());
    setTimeout(
      function() {
        showWordList(wl);
      },
      2000
    );
  }
};

showFillerTask = function() {
  $("#stimulus").hide();
  $("#fillertask-form").show();

  setTimeout(
    function() {
      showExperiment();
    },
    30000
  );
};

showExperiment = function() {
  $("#fillertask-form").hide();
  //submitResponses();
  $("#response-form").show();
  $("#send-message").removeClass("disabled");
  $("#send-message").html("Send");
  $("#reproduction").focus();
  get_transmissions();
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
      setTimeout(function () { get_transmissions(currentNodeId); }, 100);
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
      var word = resp.info.contents.toLowerCase();
      // if word hasn't appeared before, load into unique array and display
      if (uniqueWords.indexOf(word) === -1) {
        uniqueWords.push(word);
        $("#reply").append("<p>" + word + "</p>");
      }
    },
    error: function (err) {
      errorResponse = JSON.parse(err.response);
      $("body").html(errorResponse.html);
    }
  });
};

send_message = function() {
  response = $("#reproduction").val();
  // typing box
  // don't let people submit an empty response
  if (response.length === 0) {
    return;
  }

  // let people submit only if word doesn't have a space
  if (response.indexOf(" ") >= 0) {
    $("#send-message").removeClass("disabled");
    $("#send-message").html("Send");
    return;
  }

  // will not let you add a word that is non-unique
  if (uniqueWords.indexOf(response.toLowerCase()) === -1) {
    uniqueWords.push(response.toLowerCase());
    $(
      "#reply"
    ).append("<p style='color: #1693A5;'>" + response.toLowerCase() + "</p>");
  } else {
    $("#send-message").removeClass("disabled");
    $("#send-message").html("Send");
    return;
  }

  $("#reproduction").val("");
  $("#reproduction").focus();

  reqwest({
    url: "/info/" + currentNodeId,
    method: "post",
    data: { contents: response, info_type: "Info" },
    success: function(resp) {
      $("#send-message").removeClass("disabled");
      $("#send-message").html("Send");
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
