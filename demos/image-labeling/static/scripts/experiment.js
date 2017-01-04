// Consent to the experiment.
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

    // Consent to the experiment.
    $("#go-to-experiment").click(function() {
        allow_exit();
        window.location.href = '/exp';
    });

    // Submit the questionnaire.
    $("#submit-questionnaire").click(function() {
        submitResponses();
    });

    $("#submit-response").click(function() {
        $("#submit-response").addClass('disabled');
        $("#submit-response").html('Sending...');

        response = $("#reproduction").val();

        $("#reproduction").val("");

        reqwest({
            url: "/info/" + my_node_id,
            method: 'post',
            data: {
                contents: response,
                info_type: "Info"
            },
            success: function (resp) {
                create_agent();
            }
        });
    });

    // Submit the questionnaire.
    $("#submit-questionnaire").click(function() {
        submitResponses();
    });
});

// Create the agent.
create_agent = function() {
    reqwest({
        url: "/node/" + participant_id,
        method: 'post',
        type: 'json',
        success: function (resp) {
            my_node_id = resp.node.id;
            get_info(my_node_id);
        },
        error: function (err) {
            console.log(err);
            errorResponse = JSON.parse(err.response);
            if (errorResponse.hasOwnProperty('html')) {
                $('body').html(errorResponse.html);
            } else {
                allow_exit();
                go_to_page('questionnaire');
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
            document.getElementById('photograph').setAttribute(
                'src',
                'data:image/jpeg;charset=utf-8;base64,' + resp.infos[0].contents
            );
            $("#stimulus").show();
            $("#response-form").show();
        },
        error: function (err) {
            console.log(err);
            errorResponse = JSON.parse(err.response);
            $('body').html(errorResponse.html);
        }
    });
};
