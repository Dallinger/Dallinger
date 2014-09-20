Template.gameInterface.created = function () {

    paper = Raphael(0, 50, 600, 400);

    inset = 1;

    // Draw the X bar background.
    backgroundX = paper.rect(50, 50, 300, 25-2*inset);
    backgroundX.attr("stroke", "#CCCCCC");
    backgroundX.attr("stroke-dasharray", "--");
    backgroundX.hide();

    // Draw the X bar.
    stimulusX = paper.rect(50, 50-inset, 0, 25);
    stimulusX.attr("fill", "#0B486B");
    stimulusX.attr("stroke", "none");
    stimulusX.hide();

    // Draw the Y bar background.
    backgroundY = paper.rect(450, 400-300, 25-2*inset, 300);
    backgroundY.attr("stroke", "#CCCCCC");
    backgroundY.attr("stroke-dasharray", "--");
    backgroundY.hide();

    // Draw the Y bar.
    stimulusY = paper.rect(450-inset, 400, 25, 0);
    stimulusY.attr("fill", "#C02942");
    stimulusY.attr("stroke", "none");
    stimulusY.hide();

    // Draw the feedback bar.
    feedback = paper.rect(500, 400, 25, 0);
    feedback.attr("fill", "#CCCCCC");
    feedback.attr("stroke", "none");
    feedback.hide();
};

Template.gameInterface.interface = function () {

    if(Session.get("trialsCompleted") >= 0) {
        PPU = 3;  // Scaling of the stimulus

        // Adjust the X bar.
        if(Session.get("trialsCompleted") < Session.get("N")/2) {
            x = xTrain[Session.get("trialsCompleted")];
        } else {
            x = xTest[Session.get("trialsCompleted") - N/2];
        }
        stimulusXSize = x * PPU;
        stimulusX.attr({ width: stimulusXSize });

        // Adjust the Y bar.
        stimulusYSize = bounds(400 - Session.get("mouseY"), 1*PPU, xMax*PPU);
        stimulusY.attr({ y: 400 - stimulusYSize,
                    height: stimulusYSize });

        // Show the feedback bar.
        if(Session.get("enteredResponse") &&
         !Session.get("finishedTheTrial") &&
         (Session.get("trialsCompleted") < Session.get("N")/2)) {
            y = yTrain[Session.get("trialsCompleted")];
            feedback.attr({ y: 400 - y * PPU, height: y * PPU });
            feedback.show();
        }
    }
};

// Runs an individual trial of the function learning tast.
showNextStimulus = function () {

    // Clean up the stimuli from the previous trial, update state.
    Mousetrap.pause();
    Session.set("trialsCompleted", Session.get("trialsCompleted")+1);
    Session.set("enteredResponse", false);
    Session.set("finishedTheTrial", false);

    // If the experiment is over, display the completion code.
    if(Session.get("trialsCompleted") === N) {
        console.log("Experiment completed.");

        Meteor.call("setVisible", Session.get("agentUUID"));

        Mousetrap.pause();
        paper.remove();

        // JSONify the data for exporting
        var testData = {};
        for(var i in xTest) {
            testData[xTest[i]] = yTest[i];
        }
        contentsOut = JSON.stringify(testData);
        console.log(contentsOut);
        Meteor.call(
            'createInfo',
            Session.get("agentUUID"),
            contentsOut,
            function (error, result) {
                console.log(error);
                console.log(result);
            }
        );

    } else {
        // Record the current time.
        presentedAt = now();

        backgroundX.show();
        backgroundY.show();
        stimulusX.attr({width: 0});
        stimulusX.show();
        stimulusY.show();
    }
};
