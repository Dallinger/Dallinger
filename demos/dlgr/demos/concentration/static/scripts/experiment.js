var my_node_id;

// Create the agent.
create_agent = function() {
  dallinger.createAgent()
    .done(function (resp) {
      my_node_id = resp.node.id;
      game = new Game(15, 20, 30);
      game.run();
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

createInfo = function (info_type, contents) {
  dallinger.createInfo(my_node_id, {
    contents: contents,
    info_type: info_type
  });
};
