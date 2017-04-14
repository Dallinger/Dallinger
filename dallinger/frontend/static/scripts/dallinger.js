// load essential variables
var getUrlParameter = function getUrlParameter(sParam) {
    var sPageURL = decodeURIComponent(window.location.search.substring(1)),
        sURLVariables = sPageURL.split("&"),
        sParameterName,
        i;

    for (i = 0; i < sURLVariables.length; i++) {
        sParameterName = sURLVariables[i].split("=");

        if (sParameterName[0] === sParam) {
            return sParameterName[1] === undefined ? true : sParameterName[1];
        }
    }
};
var hit_id = getUrlParameter("hit_id");
var worker_id = getUrlParameter("worker_id");
var assignment_id = getUrlParameter("assignment_id");
var mode = getUrlParameter("mode");
var participant_id = getUrlParameter("participant_id");

// stop people leaving the page
window.onbeforeunload = function() {
    return "Warning: the study is not yet finished. " +
    "Closing the window, refreshing the page or navigating elsewhere " +
    "might prevent you from finishing the experiment.";
};

// allow actions to leave the page
var allow_exit = function() {
    window.onbeforeunload = function() {};
};

// advance the participant to a given html page
var go_to_page = function(page) {
    window.location = "/" + page + "?participant_id=" + participant_id;
};

// report assignment complete
var submitAssignment = function() {
    reqwest({
        url: "/participant/" + participant_id,
        method: "get",
        type: "json",
        success: function (resp) {
            mode = resp.participant.mode;
            hit_id = resp.participant.hit_id;
            assignment_id = resp.participant.assignment_id;
            worker_id = resp.participant.worker_id;
            var worker_complete = '/worker_complete';
            reqwest({
                url: worker_complete,
                method: "get",
                type: "json",
                data: {
                    "uniqueId": worker_id + ":" + assignment_id
                },
                success: function (resp) {
                    allow_exit();
                    window.location = "/complete";
                },
                error: function (err) {
                    console.log(err);
                    var errorResponse = JSON.parse(err.response);
                    $("body").html(errorResponse.html);
                }
            });
        }
    });
};

var submit_assignment = function () {
    submitAssignment();
};

// make a new participant
var create_participant = function() {
    var url;
    // check if the local store is available, and if so, use it.
    if (typeof store != "undefined") {
        url = "/participant/" +
            store.get("worker_id") + "/" +
            store.get("hit_id") + "/" +
            store.get("assignment_id") + "/" +
            store.get("mode");
    } else {
        url = "/participant/" +
            worker_id + "/" +
            hit_id + "/" +
            assignment_id + "/" +
            mode;
    }

    var deferred = $.Deferred();
    if (participant_id !== undefined && participant_id !== 'undefined') {
        deferred.resolve();
    } else {
        $(function () {
            $('.btn-success').prop('disabled', 'disabled');
            reqwest({
                url: url,
                method: "post",
                type: "json",
                success: function(resp) {
                    console.log(resp);
                    participant_id = resp.participant.id;
                    if (resp.quorum) {
                        if (resp.quorum.n === resp.quorum.q) {
                            // reached quorum; resolve immediately
                            deferred.resolve();
                        } else {
                            // wait for quorum, then resolve
                            updateProgressBar(resp.quorum.n, resp.quorum.q);
                            waitForQuorum().done(function () {
                                deferred.resolve();
                            });
                        }
                    } else {
                        // no quorum; resolve immediately
                        deferred.resolve();
                    }
                },
                error: function (err) {
                    var errorResponse = JSON.parse(err.response);
                    $("body").html(errorResponse.html);
                }
            });
        });
    }
    return deferred;
};

var lock = false;

var submitResponses = function () {
    submitNextResponse(0);
    submitAssignment();
};

var submit_responses = function () {
    submitResponses();
    submitAssignment();
};

var submitNextResponse = function (n) {

    // Get all the ids.
    var ids = $("form .question select, input, textarea").map(
        function () {
            return $(this).attr("id");
        }
    );

    reqwest({
        url: "/question/" + participant_id,
        method: "post",
        type: "json",
        data: {
            question: $("#" + ids[n]).attr("name"),
            number: n + 1,
            response: $("#" + ids[n]).val()
        },
        success: function() {
            if (n <= ids.length) {
                submitNextResponse(n + 1);
            }
        },
        error: function (err) {
            var errorResponse = JSON.parse(err.response);
            if (errorResponse.hasOwnProperty("html")) {
                $("body").html(errorResponse.html);
            }
        }
    });
};

waitForQuorum = function () {
    var ws_scheme = (window.location.protocol === "https:") ? 'wss://' : 'ws://';
    var socket = new ReconnectingWebSocket(ws_scheme + location.host + "/chat");
    var deferred = $.Deferred();
    socket.onmessage = function (msg) {
        if (msg.data.indexOf('quorum:') !== 0) { return; }
        var data = JSON.parse(msg.data.substring(7));
        var n = data.n;
        var quorum = data.q;
        updateProgressBar(n, quorum);
        if (n >= quorum) {
            deferred.resolve();
        }
    };
    return deferred;
};

updateProgressBar = function (value, total) {
    var percent = Math.round((value / total) * 100.0) + '%';
    $("#waiting-progress-bar").css("width", percent);
    $("#progress-percentage").text(percent);
};
