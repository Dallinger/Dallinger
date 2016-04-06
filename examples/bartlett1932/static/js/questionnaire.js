lock = false;

submit_responses = function() {
    if (lock===false) {
        lock=true;
        reqwest({
            url: "/question/" + participant_id,
            method: 'post',
            type: 'json',
            data: {
                question: "engagement",
                question_id: 1,
                response: $("#engagement").val()
            },
            success: function (resp) {
                reqwest({
                    url: "/question/" + participant_id,
                    method: 'post',
                    type: 'json',
                    data: {
                        question: "difficulty",
                        question_id: 2,
                        response: $("#difficulty").val()
                    },
                    success: function(resp) {
                        submit_assignment();
                    },
                    error: function (err) {
                        err_response = JSON.parse(err.response);
                        if (err_response.hasOwnProperty('html')) {
                            $('body').html(err_response.html);
                        }
                    }
                });
            },
            error: function (err) {
                console.log(err);
                err_response = JSON.parse(err.response);
                if (err_response.hasOwnProperty('html')) {
                    $('body').html(err_response.html);
                }
            }
        });
    }
};