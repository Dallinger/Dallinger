// Create the agent.
create_agent = function() {
    reqwest({
        url: "/node/" + participant_id,
        method: 'post',
        type: 'json',
        success: function (resp) {
            my_node_id = resp.node.id;
            $("#canvas").hide();
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
            $("#editor").width(300).height(300);
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
