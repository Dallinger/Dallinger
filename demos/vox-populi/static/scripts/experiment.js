// Create the agent.
create_agent = function() {
    reqwest({
        url: "/node/" + participant_id,
        method: 'post',
        type: 'json',
        success: function (resp) {
            my_node_id = resp.node.id;
            $("#response-form").show();
            $("#submit-response").removeClass('disabled');
            $("#submit-response").html('Submit');
        },
        error: function (err) {
            console.log(err);
            err_response = JSON.parse(err.response);
            if (err_response.hasOwnProperty('html')) {
                $('body').html(err_response.html);
            } else {
                allow_exit();
                go_to_page('questionnaire');
            }
        }
    });
};

submit_response = function() {

    $("#submit-response").addClass('disabled');
    $("#submit-response").html('Sending...');

    responses = {};
    for (var i = 0; i < 8; i++) {
        responses["Q" + (i + 1)] = $("#Q" + (i + 1)).val();
    }

    console.log(responses);

    reqwest({
        url: "/info/" + my_node_id,
        method: 'post',
        data: {
            contents: JSON.stringify({
                "responses": responses
            }),
            info_type: "Info"
        },
        success: function (resp) {
            create_agent();
        }
    });
};
