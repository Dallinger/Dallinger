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

finish_reading = function() {
    $("#stimulus").hide();
    $("#response-form").show();
    $("#submit-response").removeClass('disabled');
    $("#submit-response").html('Submit');
};

submit_response = function() {
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
};
