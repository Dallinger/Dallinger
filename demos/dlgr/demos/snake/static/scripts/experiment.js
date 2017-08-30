var my_node_id;

// Consent to the experiment.
$(document).ready(function() {

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

    window.location.href = '/instructions';
  });

  // Consent to the experiment.
  $("#no-consent").click(function() {
    self.close();
  });

  // Consent to the experiment.
  $("#go-to-experiment").click(function() {
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

    response = $("#reproduction").val();

    $("#reproduction").val("");

    dallinger.createInfo(my_node_id, {
      contents: response,
      info_type: "Info"
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
create_agent = function() {
  dallinger.createAgent()
    .done(function (resp) {
      my_node_id = resp.node.id;
      game = new Game(15, 20, 30);
      game.run();
    })
    .fail(function () {
      dallinger.goToPage('questionnaire');
    });
};

createInfo = function (info_type, contents) {
  dallinger.createInfo(my_node_id, {
    contents: contents,
    info_type: info_type
  });
};
