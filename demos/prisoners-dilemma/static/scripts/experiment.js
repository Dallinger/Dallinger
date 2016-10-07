$(document).ready(function() {

    // Print the consent form.
    $("#print-consent").click(function() {
        console.log("hello");
        window.print();
    });

    // Consent to the experiment.
    $("#consent").click(function() {
        store.set("hit_id", getUrlParameter("hit_id"));
        store.set("worker_id", getUrlParameter("worker_id"));
        store.set("assignment_id", getUrlParameter("assignment_id"));
        store.set("mode", getUrlParameter("mode"));

        allow_exit();
        window.location.href = '/instructions';
    });

    // Consent to the experiment.
    $("#no-consent").click(function() {
        allow_exit();
        self.close();
    });

    // Proceed to the waiting room.
    $("#go-to-waiting-room").click(function() {
        allow_exit();
        window.location.href = '/waiting';
    });

    // Send a message.
    $("#send-message").click(function() {
        send_message();
    });

    // Leave the chatroom.
    $("#leave-chat").click(function() {
        leave_chatroom();
    });

    // Submit the questionnaire.
    $("#submit-questionnaire").click(function() {
        console.log("hello");
        submitResponses();
    });

    // Cooperate.
    $("#cooperate").click(function() {
        console.log("Cooperate.");
        act("cooperate");
    });

    // Defect.
    $("#defect").click(function() {
        console.log("Defect.");
        act("defect");
    });
});

act = function (action) {
    reqwest({
        url: "/info/" + my_node_id,
        method: "post",
        data: {
            contents: action,
            info_type: "Info",
        },
        success: function (resp) {
            console.log(action);
            allow_exit();
            go_to_page("questionnaire");
        }
    });
};

// Create the agent.
create_agent = function () {
    reqwest({
        url: "/node/" + participant_id,
        method: "post",
        type: "json",
        success: function (resp) {
            my_node_id = resp.node.id;
            console.log(my_node_id);
            $("#response-form").show();
        },
        error: function (err) {
            console.log(err);
            errorResponse = JSON.parse(err.response);
            if (errorResponse.hasOwnProperty("html")) {
                $("body").html(errorResponse.html);
            } else {
                allow_exit();
                go_to_page("questionnaire");
            }
        }
    });
};

quorum = 1e6;
getQuorum = function () {
    reqwest({
        url: "/experiment/quorum",
        method: "get",
        success: function (resp) {
            quorum = resp.quorum;
        }
    });
};

waitForQuorum = function () {
    reqwest({
        url: "/summary",
        method: "get",
        success: function (resp) {
            summary = resp.summary;
            n = numReady(resp.summary);
            percent = Math.round((n/quorum)*100.0) + "%";
            $("#waiting-progress-bar").css("width", percent);
            $("#progress-percentage").text(percent);
            if (n >= quorum) {
                allow_exit();
                go_to_page("exp");
            } else {
                setTimeout(function(){
                    waitForQuorum();
                }, 1000);
            }
        }
    });
};

numReady = function(summary) {
    for (var i = 0; i < summary.length; i++) {
        if (summary[i][0] == "working") {
            return summary[i][1];
        }
    }
};
