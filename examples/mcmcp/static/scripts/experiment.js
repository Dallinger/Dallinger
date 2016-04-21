// Create the agent.
create_agent = function() {
    reqwest({
        url: "/node/" + participant_id,
        method: 'post',
        type: 'json',
        success: function (resp) {
            my_node_id = resp.node.id;
            get_infos(my_node_id);
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

get_infos = function() {
    reqwest({
        url: "/node/" + my_node_id + "/infos",
        method: 'get',
        type: 'json',
        success: function (resp) {
            vector_0 = resp.infos[0].contents;
            $("#vector_0").html(vector_0);
            vector_1 = resp.infos[1].contents;
            $("#vector_1").html(vector_1);
            $(".submit-response").attr('disabled',false);
        },
        error: function (err) {
            console.log(err);
            err_response = JSON.parse(err.response);
            $('body').html(err_response.html);
        }
    });
};

submit_response = function(choice) {
    $(".submit-response").attr('disabled',true);

    reqwest({
        url: "/record_choice/" + my_node_id + "/" + choice,
        method: 'post',
        success: function (resp) {
            create_agent();
        },
        error: function (resp) {
            create_agent();
        }
    });
};
