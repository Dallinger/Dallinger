var my_node_id;

// Create the agent.
create_agent = function() {
  dallinger.createAgent()
    .done(function (resp) {
      my_node_id = resp.node.id;
      get_info();
    })
    .fail(function () {
      dallinger.goToPage('questionnaire');
    });
};

get_info = function() {
  dallinger.getReceivedInfo(my_node_id).done(function (resp) {
    contents = JSON.parse(resp.infos[0].contents);
    console.log(contents);
    $("#image").attr("src", contents.image);
    $("#stimulus").show();
    $("#canvas").hide();
    $("#response-form").hide();
    $("#finish-reading").show();
  });
};

finish_reading = function() {
  $("#stimulus").hide();
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
