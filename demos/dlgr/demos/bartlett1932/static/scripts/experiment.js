var my_node_id;

// Consent to the experiment.
$(document).ready(function() {

  // do not allow user to close or reload
  dallinger.preventExit = true;

  // Print the consent form.
  $("#print-consent").click(function() {
    console.log("hello");
    window.print();
  });

  // Consent to the experiment.
  $("#consent").click(function() {
    store.set("hit_id", dallinger.getUrlParameter("hit_id"));
    store.set("worker_id", dallinger.getUrlParameter("worker_id"));
    store.set("assignment_id", dallinger.getUrlParameter("assignment_id"));
    store.set("mode", dallinger.getUrlParameter("mode"));

    dallinger.allowExit();
    window.location.href = '/instructions';
  });

  // Consent to the experiment.
  $("#no-consent").click(function() {
    dallinger.allowExit();
    window.close();
  });

  // Consent to the experiment.
  $("#go-to-experiment").click(function() {
    dallinger.allowExit();
    window.location.href = '/exp';
  });

  // Submit the questionnaire.
  $("#submit-questionnaire").click(function() {
    dallinger.submitResponses();
  });

  $("#finish-reading").click(function() {
    $("#stimulus").hide();
    $("#response-form").show();
    $("#submit-response").removeClass('disabled');
    $("#submit-response").html('Submit');
  });

  $("#submit-response").click(function() {
    $("#submit-response").addClass('disabled');
    $("#submit-response").html('Sending...');

    var response = $("#reproduction").val();

    $("#reproduction").val("");

    dallinger.createInfo(my_node_id, {
      contents: response,
      info_type: 'Info'
    }).done(function (resp) {
      create_agent();
    });
  });

  // Submit the questionnaire.
  $("#submit-questionnaire").click(function() {
    dallinger.submitResponses();
  });
});

// Create the agent.
var create_agent = function() {
  $('#finish-reading').prop('disabled', true);
  dallinger.createAgent()
    .done(function (resp) {
      $('#finish-reading').prop('disabled', false);
      my_node_id = resp.node.id;
      get_info();
    })
    .fail(function () {
      dallinger.allowExit();
      dallinger.goToPage('questionnaire');
    });
};

var get_info = function() {
  dallinger.getReceivedInfo(my_node_id)
    .done(function (resp) {
      var story = resp.infos[0].contents;
      var storyHTML = markdown.toHTML(story);
      $("#story").html(storyHTML);
      $("#stimulus").show();
      $("#response-form").hide();
      $("#finish-reading").show();
    })
    .fail(function (err) {
      console.log(err);
      var errorResponse = JSON.parse(err.response);
      $('body').html(errorResponse.html);
    });
};
