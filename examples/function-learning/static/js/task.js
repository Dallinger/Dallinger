// Settings
PPU = 3;      // Pixels per base unit.
xMax = 100;   // Maximum size of a bar in base units.
trialIndex = 0;
stimulusYSize = 0;



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

            // Get training values
            xTrain = data.x;
            yTrain = data.y;

            N = xTrain.length * 2;
            $("#total-trials").html(N);
            yTrainReported = [];

            // Get test values.
            // half are from training the rest are new
            allX = range(1, xMax);
            xTestFromTraining = randomSubset(xTrain, N/4);
            xTestNew = randomSubset(allX.diff(xTrain), N/4);
            xTest = shuffle(xTestFromTraining.concat(xTestNew));
            yTest = [];
            drawUserInterface();
            proceedToNextTrial();
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

    // Draw the X bar.
    stimulusX = paper.rect(50, 50-inset, 0, 25);
    stimulusX.attr("fill", "#0B486B");
    stimulusX.attr("stroke", "none");

    // Draw the Y bar background.
    backgroundY = paper.rect(450, 400-300, 25-2*inset, 300);
    backgroundY.attr("stroke", "#CCCCCC");
    backgroundY.attr("stroke-dasharray", "--");

    // Draw the Y bar.
    stimulusY = paper.rect(450-inset, 400, 25, 0);
    stimulusY.attr("fill", "#C02942");
    stimulusY.attr("stroke", "none");

    // Draw the feedback bar.
    feedback = paper.rect(500, 400, 25, 0);
    feedback.attr("fill", "#CCCCCC");
    feedback.attr("stroke", "none");
    feedback.hide();

    if (trialIndex === 0) {
        // Track the mouse.
        $(document).mousemove( function(e) {
            y = e.pageY-50;
            stimulusYSize = bounds(400 - y, 1*PPU, xMax*PPU);
            stimulusY.attr({ y: 400 - stimulusYSize, height: stimulusYSize });
        });

        Mousetrap.bind("space", proceedToNextTrial, "keydown");
        document.addEventListener('click', mousedownEventListener);
    }
};

proceedToNextTrial = function () {
    // Prevent repeat keypresses.
    Mousetrap.pause();

    // Increment the trial counter.
    trialIndex = trialIndex + 1;
    $("#trial-number").html(trialIndex);

    // Set up the stimuli.
    if (trialIndex < N/2)
        stimulusXSize = xTrain[trialIndex - 1] * PPU;
    else
        stimulusXSize = xTest[trialIndex - N/2 - 1] * PPU;
    stimulusX.attr({ width: stimulusXSize });
    stimulusX.show();
    stimulusY.show();

    // If this was the last trial, finish up.
    if (trialIndex == N+1) {
        document.removeEventListener('click', mousedownEventListener);
        paper.remove();

        // Send data back to the server.
        response = JSON.stringify({"x": xTest, "y": yTest});

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
    } else {
        clicked = false;
    }
};

//
// Listen for clicks and act accordingly.
//
function mousedownEventListener(event) {
    if (clicked === false) {

        yNow = Math.round(stimulusYSize/PPU);

        // Training phase
        if (trialIndex < N/2) {
            yTrue = yTrain[trialIndex-1];
            // if they are wrong show feedback
            yTrainReported.push(yNow);
            feedback.attr({ y: 400 - yTrue * PPU, height: yTrue * PPU });
            feedback.show();
            feedback.animate({fill: "#666"}, 100, "<", function () {
                this.animate({fill: "#CCC"}, 100, ">");
            });
            // Move on to next trial if response is correct.
            if(Math.abs(yNow - yTrue) < 4) {
                clicked = true;
                feedback.hide();
                stimulusX.hide();
                stimulusY.hide();
                Mousetrap.resume();
            }
        // Testing phase
        } else if (trialIndex <= N) {
            clicked = true;
            $("#training-or-testing").html("Testing");
            yTest.push(yNow);
            feedback.hide();
            stimulusX.hide();
            stimulusY.hide();
            Mousetrap.resume();
        }
    }
}
