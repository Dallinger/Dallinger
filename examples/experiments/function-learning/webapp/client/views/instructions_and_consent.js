  Template.instructionsAndConsent.rendered = function () {
    $("#consentModal").modal('show');
  };

  // Once the user gives consent, we set up the experiment.
  Template.instructionsAndConsent.events({

    "click #giveConsent": function(event) {
      console.log("Participant consented.");
      Session.set("isConsensual", true);

      // TODO: Put these nested calls on the server side.
      Meteor.call("createAgent", function(error, results) {
        agent_content = EJSON.parse(results.content);
        Session.set("agentUUID", agent_content.agents.uuid);
        amplify.store("agentUUID", agent_content.agents.uuid);

        // Get this participant's training and test data.
        Meteor.call(
            "getPendingTransmissions",
            Session.get("agentUUID"),
            function(error, results) {
                transmission_content = EJSON.parse(results.content);
                t_uuid = transmission_content.transmissions[0].info_uuid;

                Meteor.call(
                    "getInfo",
                    t_uuid,
                    function (error, results) {
                        info_content = EJSON.parse(results.content);
                        data = EJSON.parse(info_content.contents);
                        xTrain = Object.keys(data).map(
                            function (x) {
                                return parseInt(x, 10);
                            }
                        );

                        yTrain = Object.keys(data).map(
                            function (x) {
                                return parseInt(data[x], 10);
                            }
                        );

                      Session.set("N", 2 * xTrain.length);
                      var N = Session.get("N"); // Total number of trials
                      assert(N%4 === 0, "Number of trials must be divisible by 4.");

                      allX = range(1, xMax);
                      xTestFromTraining = randomSubset(xTrain, N/4);
                      xTestNew = randomSubset(allX.diff(xTrain), N/4);
                      xTest = shuffle(xTestFromTraining.concat(xTestNew));
                      yTrainReported = [];
                      yTest = [];

                      Mousetrap.bind("space", showNextStimulus, "keydown");
                      showNextStimulus();
                    }
                );
            }
        );
      }
  );
    }
  });
