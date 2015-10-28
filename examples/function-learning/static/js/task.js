var psiTurk = new PsiTurk(uniqueId, adServerLoc, mode);

var mycondition = condition;
var mycounterbalance = counterbalance;

var pages = [
    "instructions/instruct-1.html",
    "instructions/instruct-2.html",
    "instructions/instruct-3.html",
	"instructions/instruct-ready.html",
	"stage.html",
	"postquestionnaire.html",
    "tampering.html"
];

psiTurk.preloadPages(pages);

var instructionPages = [
    "instructions/instruct-1.html",
    "instructions/instruct-2.html",
    "instructions/instruct-3.html",
	"instructions/instruct-ready.html"
];

//
// Function learning task.
//
var FunctionLearningExperiment = function() {

    // Kick people out if they change their workerId.
    function ensureSameWorker() {
        workerId = amplify.store("wallace_worker_id");
        workerIdNew = getParameterByName('workerId');

        if (typeof workerId === 'undefined') {
            amplify.store("wallace_worker_id", workerIdNew);
        } else {
            if ((workerIdNew !== workerId) && (workerIdNew.substring(0,5) !== "debug")) {
                currentview = psiTurk.showPage('tampering.html');
            }
        }
    }

	// Settings
	PPU = 3;      // Pixels per base unit.
	xMax = 100;   // Maximum size of a bar in base units.


    // Create the agent.
    createAgent = function() {

        ensureSameWorker();

        reqwest({
            url: "/node/" + uniqueId,
            method: 'post',
            type: 'json',
            success: function (resp) {
                my_node_id = resp.node.id;
                getPendingTransmissions(my_node_id);
            },
            error: function (err) {
                console.log(err);
                err_response = JSON.parse(err.response);
                if (err_response.hasOwnProperty('html')) {
                    $('body').html(err_response.html);
                } else {
                    currentview = new Questionnaire();
                }
            }
        });
    };

    getPendingTransmissions = function(my_node_id) {
        reqwest({
            url: "/transmission/" + uniqueId + "/" + my_node_id,
            method: 'get',
            data: { status: "pending", direction: "incoming" },
            type: 'json',
            success: function (resp) {
                info_id = resp.transmissions[0].info_id;
                info = getInfo(info_id);
            },
            error: function (err) {
                console.log(err);
                err_response = JSON.parse(err.response);
                $('body').html(err_response.html);
            }
        });
    };

    getInfo = function(info_id) {
        reqwest({
            url: "/info/" + uniqueId + "/" + my_node_id,
            method: 'get',
            data: { info_id: info_id },
            type: 'json',
            success: function (resp) {
                story = resp.infos[0].contents;
                storyHTML = markdown.toHTML(story);
                $("#story").html(storyHTML);
                $("#stimulus").show();
                $("#response-form").hide();
                $("#finish-reading").show();
            },
            error: function (err) {
                console.log(err);
                err_response = JSON.parse(err.response);
                $('body').html(err_response.html);
            }
        });
    };

	getInfo = function(info_id) {
		reqwest({
            url: "/info/" + uniqueId + "/" + my_node_id,
            method: 'get',
            data: { info_id: info_id },
            type: 'json',
            success: function (resp) {

                r = resp.info.contents;

                console.log(r);

                data = JSON.parse(r);

                console.log(data);

                // Set training variables.
                xTrain = data.x;
                yTrain = data.y;
                console.log(xTrain);
                console.log(yTrain);

                N = xTrain.length * 2;
                $("#total-trials").html(N);
                yTrainReported = [];

                // Set testing variables.
                allX = range(1, xMax);
                xTestFromTraining = randomSubset(xTrain, N/4);
                xTestNew = randomSubset(allX.diff(xTrain), N/4);
                xTest = shuffle(xTestFromTraining.concat(xTestNew));
                yTest = [];
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
            console.log("Trial " + (1 + trialIndex) + " completed.");
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
                    url: "/info/" + uniqueId + "/" + my_node_id,
                    method: 'post',
                    data: {
                        contents: response,
                        info_type: "Info"
                    }
                });

                // Show the questionnaire.
                currentview = new Questionnaire();
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
                    console.log("Successful correction.");
                    readyToProceedToNextTrial = true;
                    feedback.hide();
                    stimulusX.hide();
                    stimulusY.hide();
                    Mousetrap.resume();
                } else {  // Show animation for failed correction.
                    feedback.animate({fill: "#666"}, 100, "<", function () {
                        this.animate({fill: "#CCC"}, 100, ">");
                    });
                    console.log("Failure to correct.");
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

        // Adjust the Y bar.
        y = e.pageY-50;
        stimulusYSize = bounds(400 - y, 1*PPU, xMax*PPU);
        stimulusY.attr({ y: 400 - stimulusYSize, height: stimulusYSize });
    });

	//
    // Start the experiment.
	//
	trialIndex = 0;
    N = Infinity;
    stimulusYSize = 0;
	enteredResponse = false;
    createAgent();
	psiTurk.showPage('stage.html');
    drawUserInterface();
    Mousetrap.bind("space", proceedToNextTrial, "keydown");
    window.setTimeout(function () {
        document.addEventListener('click', mousedownEventListener);
        stimulusXSize = xTrain[trialIndex] * PPU;
        stimulusX.attr({ width: stimulusXSize });
    }, 500);
};

//
//  Questionnaire at the end of the experiment.
//
var Questionnaire = function() {

	var error_message = "<h1>Oops!</h1><p>Something went wrong submitting your HIT. This might happen if you lose your internet connection. Press the button to resubmit.</p><button id='resubmit'>Resubmit</button>";

	record_responses = function() {

		psiTurk.recordTrialData({'phase':'postquestionnaire', 'status':'submit'});

		$('textarea').each( function(i, val) {
			psiTurk.recordUnstructuredData(this.id, this.value);
		});
		$('select').each( function(i, val) {
			psiTurk.recordUnstructuredData(this.id, this.value);
		});

	};

	prompt_resubmit = function() {
		replaceBody(error_message);
		$("#resubmit").click(resubmit);
	};

	resubmit = function() {
		replaceBody("<h1>Trying to resubmit...</h1>");
		reprompt = setTimeout(prompt_resubmit, 10000);

		psiTurk.saveData({
			success: function() {
			    clearInterval(reprompt);
                psiTurk.computeBonus('compute_bonus', function(){finish();});
			},
		});
	};

	// Load the questionnaire snippet
	psiTurk.showPage('postquestionnaire.html');
	psiTurk.recordTrialData({'phase':'postquestionnaire', 'status':'begin'});

	$("#next").click(function () {
        $('#next').prop('disabled', true);
        $("#next-symbol").attr('class', 'glyphicon glyphicon-refresh glyphicon-refresh-animate');
	    record_responses();
	    psiTurk.saveData({
            success: function(){
                psiTurk.computeBonus('compute_bonus', function() {
                	psiTurk.completeHIT(); // when finished saving compute bonus, the quit
                });
            },
            error: prompt_resubmit});
	});
};

//
// Run Task
//
var currentview;

$(window).load( function(){
    psiTurk.doInstructions(
        instructionPages,
        function() { currentview = new FunctionLearningExperiment(); }
    );
});
