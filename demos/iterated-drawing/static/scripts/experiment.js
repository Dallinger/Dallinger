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
            contents = JSON.parse(resp.infos[0].contents);
            console.log(contents);
            $("#image").attr("src", contents.image);
            $("#stimulus").show();
            $("#canvas").hide();
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
    sketchpad = Raphael.sketchpad("editor", {
        width: 300,
        height: 300,
        editing: true
    });
    pen = sketchpad.pen();
    pen.width(2);
};

submit_response = function() {

    canvg('canvas', $("#editor").html());
    console.log(canvas.toDataURL("image/png"));

    $("#submit-response").addClass('disabled');
    $("#submit-response").html('Sending...');

    reqwest({
        url: "/info/" + my_node_id,
        method: 'post',
        data: {
            contents: JSON.stringify({
                "sketch": sketchpad.json(),
                "image": canvas.toDataURL("image/png"),
            }),
            info_type: "Info"
        },
        success: function (resp) {
            create_agent();
        }
    });
};
