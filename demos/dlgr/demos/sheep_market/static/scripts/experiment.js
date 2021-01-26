var my_node_id;

// Create the agent.
create_agent = function() {
  dallinger.createAgent()
    .done(function (resp) {
      my_node_id = resp.node.id;
      $("#canvas").hide();
      $("#response-form").show();
      $("#submit-response").removeClass('disabled');
      $("#submit-response").html('Submit');
      sketchpad = Raphael.sketchpad("editor", {
        width: 300,
        height: 300,
        editing: true
      });
      pen = sketchpad.pen();
      pen.width(2);
      $("#editor").width(300).height(300);
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

submit_response = function() {
  canvg('canvas', $("#editor").html());
  console.log(canvas.toDataURL("image/png"));

  $("#submit-response").addClass('disabled');
  $("#submit-response").html('Sending...');

  dallinger.createInfo(my_node_id, {
    contents: JSON.stringify({
      "sketch": sketchpad.json(),
      "image": canvas.toDataURL("image/png")
    }),
    info_type: "Info"
  }).done(function (resp) {
    create_agent();
  });
};
