xMax = 100;

if (Meteor.isClient) {

    Session.set("N", -1);

    Session.set("trialsCompleted", -1);
    Session.set("isConsensual", false);

    Meteor.call(
        "allAgents",
        function (error, results) {
            allAgents = EJSON.parse(results.content).agents;
            Session.set("allAgents", allAgents);
        }
    );

    Handlebars.registerHelper("isNewParticipant", function() {
        if (amplify.store("agentUUID") === undefined) {
            return true;
        } else {
            return !contains(Session.get("allAgents"), amplify.store("agentUUID"));
        }
    });

    proceedToNextTrial = function () {
        backgroundX.hide();
        backgroundY.hide();
        stimulusX.hide();
        stimulusY.hide();
        feedback.hide();
        Mousetrap.resume();
        Session.set("finishedTheTrial", true);
    };

    // Track the mouse.
    $(document).mousemove( function(e) {
        Session.set("mouseX", e.pageX);
        Session.set("mouseY", e.pageY-50);
    });

    // Listens for clicks (entered responses) and acts accordingly.
    $(document).mousedown(function(e) {

        trialIndex = Session.get("trialsCompleted");

        // Record the click if it's a response, check it if it's a correction.
        if(trialIndex >= 0 && trialIndex < N) {

            respondedAt = now();

            // Record the current response in natural units.
            yNow = stimulusYSize/PPU;
            yTrue = yTrain[trialIndex];

            if(!Session.get("enteredResponse")) {
                // add response to db
                if(trialIndex < N/2){ // Is it training?
                    yTrainReported.push(yNow);
                } else {
                    yTest.push(yNow);
                }
                Session.set("enteredResponse", true);

                // If this is a test trial, then there's no feedback, so we're done.
                if(trialIndex >= N/2) {
                    proceedToNextTrial();
                }

            } else {
                if(Math.abs(yNow - yTrue) < 5) {
                    proceedToNextTrial();
                } else { // Show animation for failed correction.
                    feedback.animate({fill: "#666"}, 100, "<", function () {
                        this.animate({fill: "#CCC"}, 100, ">");
                    });
                }
            }
        }
    });
}
