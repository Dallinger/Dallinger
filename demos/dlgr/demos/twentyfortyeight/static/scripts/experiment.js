var my_node_id;

// Create the agent.
create_agent = function() {
  dallinger.createAgent()
    .done(function (resp) {
      my_node_id = resp.node.id;
    })
    .fail(function () {
      dallinger.goToPage('questionnaire');
    });
};

$(".restart-button").hide();
