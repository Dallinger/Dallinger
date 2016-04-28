/*
 * Requires:
 *     psiturk.js
 *     utils.js
 */

// Initalize psiturk object
var psiTurk = new PsiTurk(uniqueId, adServerLoc, mode);

var mycondition = condition;  // these two variables are passed by the psiturk server process
var mycounterbalance = counterbalance;  // they tell you which condition you have been assigned to
// they are not used in the stroop code but may be useful to you

// All pages to be loaded
var pages = [
    "instructions/instruct-1.html",
    "instructions/instruct-2.html",
    "instructions/instruct-ready.html",
    "stage.html",
    "postquestionnaire.html",
    "tampering.html"
];

psiTurk.preloadPages(pages);

var instructionPages = [ // add as a list as many pages as you like
    "instructions/instruct-1.html",
    "instructions/instruct-2.html",
    "instructions/instruct-ready.html",
];

var num_practice_trials = 5;


/********************
* HTML manipulation
*
* All HTML files in the templates directory are requested
* from the server when the PsiTurk object is created above. We
* need code to get those pages from the PsiTurk object and
* insert them into the document.
*
********************/

/********************
* STROOP TEST       *
********************/
var StroopExperiment = function() {

    trial = 0;
    lock = true;

    // Kick people out if they change their workerId.
    function ensureSameWorker() {
        workerId = amplify.store("wallace_worker_id")
        workerIdNew = getParameterByName('workerId')

        if (typeof workerId === 'undefined') {
            amplify.store("wallace_worker_id", workerIdNew)
        } else {
            if ((workerIdNew != workerId) && (workerIdNew.substring(0,5) != "debug")) {
                currentview = psiTurk.showPage('tampering.html');
            }
        }
    }

    // Load the stage.html snippet into the body of the page
    psiTurk.showPage('stage.html');
    $("#response-form").hide();
    $("#finish-reading").hide();

    // Create the agent.
    createAgent = function() {

        ensureSameWorker();

        reqwest({
            url: "/node/" + uniqueId,
            method: 'post',
            type: 'json',
            success: function (resp) {
                my_node_id = resp.node.id;
                getAllInformation(my_node_id);
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

    // Get all the infos
    getAllInformation = function(my_node_id) {
        reqwest({
            url: "/node/" + my_node_id + "/infos",
            method: 'get',
            data: {info_type: "LearningGene"},
            type: 'json',
            success: function (resp) {
                learning_strategy = resp.infos[0].contents;
                getPendingTransmissions(my_node_id);
            },
            error: function (err) {
                console.log(err);
                err_response = JSON.parse(err.response);
                $('body').html(err_response.html);
            }
        });
    };

    getPendingTransmissions = function(my_node_id) {
        reqwest({
            url: "/node/" + my_node_id + "/transmissions",
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
            url: "/info/" + my_node_id + "/" + info_id,
            method: 'get',
            type: 'json',
            success: function (resp) {

                trial = trial + 1;
                $("#trial-number").html(trial);
                if (trial <= num_practice_trials) {
                    $("#practice-trial").html("This is a practice trial");
                } else {
                    $("#practice-trial").html("This is NOT a practice trial");
                }


                // Show the participant the stimulus.
                if (learning_strategy === "asocial") {

                    $("#instructions").text("Are there more blue or yellow dots?");

                    state = resp.info.contents;
                    regenerateDisplay(state);

                    $("#more-blue").addClass('disabled');
                    $("#more-yellow").addClass('disabled');

                    presentDisplay();

                    $("#stimulus-stage").show();
                    $("#response-form").hide();
                    $("#more-yellow").show();
                    $("#more-blue").show();
                }

                // Show the participant the hint.
                if (learning_strategy == "social") {

                    $("#instructions").html("Are there more blue or yellow dots?");

                    $("#more-blue").addClass('disabled');
                    $("#more-yellow").addClass('disabled');

                    meme = resp.info.contents;

                    if (meme == "blue") {
                        $("#stimulus").attr("src", "/static/images/blue_social.jpg");
                    } else if (meme == "yellow") {
                        $("#stimulus").attr("src", "/static/images/yellow_social.jpg");
                    }
                    $("#stimulus").show();
                    setTimeout(function() {
                        $("#stimulus").hide();
                        $("#more-blue").removeClass('disabled');
                        $("#more-yellow").removeClass('disabled');
                        lock = false;
                    }, 2000);
                }
            },
            error: function (err) {
                console.log(err);
                err_response = JSON.parse(err.response);
                $('body').html(err_response.html);
            }
        });
    };

    createAgent();

    function presentDisplay (argument) {
        for (var i = dots.length - 1; i >= 0; i--) {
            dots[i].show();
        }
        setTimeout(function() {
            for (var i = dots.length - 1; i >= 0; i--) {
                dots[i].hide();
            }
            $("#more-blue").removeClass('disabled');
            $("#more-yellow").removeClass('disabled');
            lock = false;
            paper.clear();
        }, 1000);

    }

    function regenerateDisplay (state) {

        // Display parameters
        width = 600;
        height = 400;
        numDots = 80;
        dots = [];
        blueDots = Math.round(state * numDots);
        yellowDots = numDots - blueDots;
        sizes = [];
        rMin = 10; // The dots' minimum radius.
        rMax = 20;
        horizontalOffset = (window.innerWidth - width) / 2;

        paper = Raphael(horizontalOffset, 200, width, height);

        colors = [];
        colorsRGB = ["#428bca", "#FBB829"];

        for (var i = blueDots - 1; i >= 0; i--) {
            colors.push(0);
        }

        for (var i = yellowDots - 1; i >= 0; i--) {
            colors.push(1);
        }

        colors = shuffle(colors);

        while (dots.length < numDots) {

            // Pick a random location for a new dot.
            r = randi(rMin, rMax);
            x = randi(r, width - r);
            y = randi(r, height - r);

            // Check if there is overlap with any other dots
            pass = true;
            for (var i = dots.length - 1; i >= 0; i--) {
                distance = Math.sqrt(Math.pow(dots[i].attrs.cx - x, 2) + Math.pow(dots[i].attrs.cy - y, 2));
                if (distance < (sizes[i] + r)) {
                    pass = false;
                }
            }

            if (pass) {
                var dot = paper.circle(x, y, r);
                dot.hide();
                // use the appropriate color.
                dot.attr("fill", colorsRGB[colors[dots.length]]); // FBB829
                dot.attr("stroke", "#fff");
                dots.push(dot);
                sizes.push(r);
            }
        }
    }

    function randi(min, max) {
        return Math.floor(Math.random() * (max - min + 1)) + min;
    }

    function shuffle(o){
        for(var j, x, i = o.length; i; j = Math.floor(Math.random() * i), x = o[--i], o[i] = o[j], o[j] = x);
        return o;
    }

    // $("#finish-reading").click(function() {
    //  $("#stimulus-stage").hide();
    //  $("#response-form").show();
    //  $("#submit-response").removeClass('disabled');
    // });

    reportBlue = function () {
        if(lock === false) {
            $("#more-blue").addClass('disabled');
            $("#more-blue").html('Sending...');
            $("#reproduction").val("");

            reqwest({
                url: "/info/" + my_node_id,
                method: 'post',
                data: {
                    contents: "blue",
                    info_type: "Meme"
                },
                success: function (resp) {
                    $("#more-blue").removeClass('disabled');
                    $("#more-blue").blur();
                    $("#more-blue").html('Blue');
                    createAgent();
                }
            });
            lock = true;
        }
    };

    reportYellow = function () {
        if(lock === false) {
            $("#more-yellow").addClass('disabled');
            $("#more-yellow").html('Sending...');
            $("#reproduction").val("");

            reqwest({
                url: "/info/" + my_node_id,
                method: 'post',
                data: {
                    contents: "yellow",
                    info_type: "Meme"
                },
                success: function (resp) {
                    $("#more-yellow").removeClass('disabled');
                    $("#more-yellow").blur();
                    $("#more-yellow").html('Yellow');
                    createAgent();
                }
            });
            lock = true;
        }
    };

    $(document).keydown(function(e) {
        var code = e.keyCode || e.which;
        if(code == 70) { //Enter keycode
            reportBlue();
        } else if (code == 74) {
            reportYellow();
        }
    });

    $("#more-yellow").click(function() {
        reportYellow();
    });

    $("#more-blue").click(function() {
        reportBlue();
    });
};

/****************
* Questionnaire *
****************/

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
                psiTurk.computeBonus('compute_bonus', function(){finish()});
            },
            error: prompt_resubmit
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
                psiTurk.completeHIT();
            },
            error: prompt_resubmit});
    });


};

// Task object to keep track of the current phase
var currentview;

/*******************
 * Run Task
 ******************/
$(window).load( function(){
    psiTurk.doInstructions(
        instructionPages, // a list of pages you want to display in sequence
        function() { currentview = new StroopExperiment(); } // what you want to do when you are done with instructions
    );
});
