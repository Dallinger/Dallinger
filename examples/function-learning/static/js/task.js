// Settings
PPU = 3;      // Pixels per base unit.
xMax = 100;   // Maximum size of a bar in base units.
trialIndex = 0;
N = Infinity;
stimulusYSize = 0;
enteredResponse = false;



// Create the agent.
create_agent = function() {
    reqwest({
        url: "/node/" + participant_id,
        method: 'post',
        type: 'json',
        success: function (resp) {
            my_node_id = resp.node.id;
            get_info();
        },
        error: function (err) {
            console.log(err);
            err_response = JSON.parse(err.response);
            if (err_response.hasOwnProperty('html')) {
                $('body').html(err_response.html);
            } else {
                allow_exit();
                go_to_page('postquestionnaire');
            }
        }
    });
};

get_info = function() {
    reqwest({
        url: "/node/" + my_node_id + "/received_infos",
        method: 'get',
        type: 'json',
        success: function (resp) {
            r = resp.infos[0].contents;
            data = JSON.parse(r);

            // Set training variables.
            xTrain = data.x;
            yTrain = data.y;

            N = xTrain.length * 2;
            $("#total-trials").html(N);
            yTrainReported = [];

            // Set testing variables.
            allX = range(1, xMax);
            xTestFromTraining = randomSubset(xTrain, N/4);
            xTestNew = randomSubset(allX.diff(xTrain), N/4);
            xTest = shuffle(xTestFromTraining.concat(xTestNew));
            yTest = [];
            drawUserInterface();
        },
        error: function (err) {
            console.log(err);
            err_response = JSON.parse(err.response);
            $('body').html(err_response.html);
        }
    });
};


//
// Draw the user interface.
//
drawUserInterface = function () {

    paper = Raphael(0, 50, 600, 400);

    inset = 1;

    // Draw the X bar background.
    backgroundX = paper.rect(50, 50, 300, 25-2*inset);
    backgroundX.attr("stroke", "#CCCCCC");
    backgroundX.attr("stroke-dasharray", "--");
    // backgroundX.hide();

    // Draw the X bar.
    stimulusX = paper.rect(50, 50-inset, 0, 25);
    stimulusX.attr("fill", "#0B486B");
    stimulusX.attr("stroke", "none");
    // stimulusX.hide();

    // Draw the Y bar background.
    backgroundY = paper.rect(450, 400-300, 25-2*inset, 300);
    backgroundY.attr("stroke", "#CCCCCC");
    backgroundY.attr("stroke-dasharray", "--");
    // backgroundY.hide();

    // Draw the Y bar.
    stimulusY = paper.rect(450-inset, 400, 25, 0);
    stimulusY.attr("fill", "#C02942");
    stimulusY.attr("stroke", "none");
    // stimulusY.hide();

    // Draw the feedback bar.
    feedback = paper.rect(500, 400, 25, 0);
    feedback.attr("fill", "#CCCCCC");
    feedback.attr("stroke", "none");
    feedback.hide();
};

proceedToNextTrial = function () {

    if (readyToProceedToNextTrial) {

        // Increment the trial counter.
        trialIndex = trialIndex + 1;
        $("#trial-number").html(trialIndex);

        // Set up the stimuli.
        if (trialIndex < N/2)
            stimulusXSize = xTrain[trialIndex] * PPU;
        else
            stimulusXSize = xTest[trialIndex - N/2] * PPU;
        stimulusX.attr({ width: stimulusXSize });
        stimulusX.show();
        stimulusY.show();

        // Prevent repeat keypresses.
        Mousetrap.pause();

        // Wait for a new response.
        enteredResponse = false;

        // If this was the last trial, finish up.
        if (trialIndex == N) {
            document.removeEventListener('click', mousedownEventListener);
            Mousetrap.pause();
            paper.remove();

            // Send data back to the server.
            response = encodeURIComponent(JSON.stringify({"x": xTest, "y": yTest}));

            reqwest({
                url: "/info/" + my_node_id,
                method: 'post',
                data: {
                    contents: response,
                    info_type: "Info"
                }, success: function(resp) {
                    create_agent();
                }
            });
        }
    }
};

//
// Listen for clicks and act accordingly.
//
function mousedownEventListener(event) {

    yNow = stimulusYSize/PPU;

    // Training phase
    if (trialIndex < N/2) {

        yTrue = yTrain[trialIndex];

        if (!enteredResponse) {
            yTrainReported.push(yNow);
            enteredResponse = true;
            feedback.attr({ y: 400 - yTrue * PPU, height: yTrue * PPU });
            feedback.show();
        } else {
            // Move on to next trial iff response is correct.
            if(Math.abs(yNow - yTrue) < 5) {
                readyToProceedToNextTrial = true;
                feedback.hide();
                stimulusX.hide();
                stimulusY.hide();
                Mousetrap.resume();
            } else {  // Show animation for failed correction.
                feedback.animate({fill: "#666"}, 100, "<", function () {
                    this.animate({fill: "#CCC"}, 100, ">");
                });
            }
        }

    // Testing phase
    } else if (trialIndex < N) {
        $("#training-or-testing").html("Testing");
        yTest.push(yNow);
        readyToProceedToNextTrial = true;
        feedback.hide();
        stimulusX.hide();
        stimulusY.hide();
        Mousetrap.resume();
    }
}

// Track the mouse.
$(document).mousemove( function(e) {
    y = e.pageY-50;
    stimulusYSize = bounds(400 - y, 1*PPU, xMax*PPU);
    stimulusY.attr({ y: 400 - stimulusYSize, height: stimulusYSize });
});

Mousetrap.bind("space", proceedToNextTrial, "keydown");
window.setTimeout(function () {
    document.addEventListener('click', mousedownEventListener);
    stimulusXSize = xTrain[trialIndex] * PPU;
    stimulusX.attr({ width: stimulusXSize });
}, 500);
