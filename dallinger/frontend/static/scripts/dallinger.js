/*
NOTE: This file is deprecated and will be removed
in the next major release of Dallinger. Update your
experiments to use dallinger2.js instead.
*/

/*globals Spinner, reqwest, store */

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


var Dallinger = (function () {
  var dlgr = {},
      participantId = getUrlParameter("participant_id");

  dlgr.submitQuestionnaire = function (name) {
    var formSerialized = $("form").serializeArray(),
        formDict = {},
        deferred = $.Deferred();

    formSerialized.forEach(function (field) {
        formDict[field.name] = field.value;
    });

    reqwest({
      method: "post",
      url: "/question/" + participantId,
      data: {
        question: name || "questionnaire",
        number: 1,
        response: JSON.stringify(formDict),
      },
      type: "json",
      success: function (resp) {
        deferred.resolve();
      },
      error: function (err) {
        deferred.reject();
        var errorResponse = JSON.parse(err.response);
        $("body").html(errorResponse.html);
      }
    });

    return deferred;
  };


  dlgr.BusyForm = (function () {

    /**
    Loads a spinner as a visual cue that something is happening
    and disables any jQuery objects passed to freeze().
    **/

    var defaults = {
      spinnerSettings: {scale: 1.5}, // See http://spin.js.org/ for all settings
      spinnerID: 'spinner',  // ID for HTML element where spinner will be inserted
    };

    var BusyForm = function (options) {
      if (!(this instanceof BusyForm)) {
          return new BusyForm(options);
      }
      var settings = $.extend(true, {}, defaults, options);
      this.spinner = new Spinner(settings.spinnerSettings);
      this.target = document.getElementById(settings.spinnerID);
      if (this.target === null) {
        throw new Error(
          'Target HTML element for spinner with ID "' + settings.spinnerID +
          '" does not exist.');
      }
      this.$elements = [];
    };

    BusyForm.prototype.freeze = function ($elements) {
      this.$elements = $elements;
      this.$elements.forEach(function ($element) {
        $element.attr("disabled", true);
      });
      this.spinner.spin(this.target);
    };

    BusyForm.prototype.unfreeze = function () {
      this.$elements.forEach(function ($element) {
        $element.attr("disabled", false);
      });
      this.spinner.stop();
      this.$elements = [];
    };


    return BusyForm;
  }());

  return dlgr;
})();

var hit_id = getUrlParameter("hit_id");
var worker_id = getUrlParameter("worker_id");
var assignment_id = getUrlParameter("assignment_id");
var mode = getUrlParameter("mode");
var participant_id = getUrlParameter("participant_id");

// stop people leaving the page, but only if desired by experiment
var allow_exit_once = false;
var prevent_exit = false;
window.addEventListener('beforeunload', function(e) {
    if (prevent_exit == true && allow_exit_once == false) {
        var returnValue = "Warning: the study is not yet finished. " +
        "Closing the window, refreshing the page or navigating elsewhere " +
        "might prevent you from finishing the experiment.";
        e.returnValue = returnValue;
        return returnValue;
    } else {
        allow_exit_once = false;
        return undefined;
    }
});

// allow actions to leave the page
var allow_exit = function() {
    allow_exit_once = true;
};

// advance the participant to a given html page
var go_to_page = function(page) {
    window.location = "/" + page + "?participant_id=" + participant_id;
};

// report assignment complete
var submitAssignment = function() {
    var deferred = $.Deferred();
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
                    deferred.resolve();
                    allow_exit();
                    window.location = "/complete";
                },
                error: function (err) {
                    deferred.reject();
                    console.log(err);
                    var errorResponse = JSON.parse(err.response);
                    $("body").html(errorResponse.html);
                }
            });
        }
    });
    return deferred;
};

var submit_assignment = function () {
    return submitAssignment();
};

// make a new participant
var create_participant = function() {
    var url;

    new Fingerprint2().get(function(result){
      fingerprint_hash = result;
      store.set("fingerprint_hash", fingerprint_hash)
    });

    // check if the local store is available, and if so, use it.
    if (typeof store != "undefined") {
        url = "/participant/" +
            store.get("worker_id") + "/" +
            store.get("hit_id") + "/" +
            store.get("assignment_id") + "/" +
            store.get("mode") + "?fingerprint_hash=" +
            store.get("fingerprint_hash");
    } else {
        url = "/participant/" +
            worker_id + "/" +
            hit_id + "/" +
            assignment_id + "/" +
            mode + "?fingerprint_hash=" + 
            fingerprint_hash;
    }

    var deferred = $.Deferred();
    if (participant_id !== undefined && participant_id !== 'undefined') {
        deferred.resolve();
    } else {
        $(function () {
            $('.btn-success').prop('disabled', true);
            reqwest({
                url: url,
                method: "post",
                type: "json",
                success: function(resp) {
                    console.log(resp);
                    $('.btn-success').prop('disabled', false);
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
    submitNextResponse(0, submitAssignment);
};

var submit_responses = function () {
    submitResponses();
};

var submitNextResponse = function (n, callback = function(){}) {

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
                submitNextResponse(n + 1, callback);
            } else {
                callback();
            }
        },
        error: function (err) {
            var errorResponse = JSON.parse(err.response);
            if (errorResponse.hasOwnProperty("html")) {
                $("body").html(errorResponse.html);
            }
            callback();
        }
    });
};

waitForQuorum = function () {
    var ws_scheme = (window.location.protocol === "https:") ? 'wss://' : 'ws://';
    var socket = new ReconnectingWebSocket(ws_scheme + location.host + "/chat?channel=quorum");
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
