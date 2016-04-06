// load essential variables
var getUrlParameter = function getUrlParameter(sParam) {
    var sPageURL = decodeURIComponent(window.location.search.substring(1)),
        sURLVariables = sPageURL.split('&'),
        sParameterName,
        i;

    for (i = 0; i < sURLVariables.length; i++) {
        sParameterName = sURLVariables[i].split('=');

        if (sParameterName[0] === sParam) {
            return sParameterName[1] === undefined ? true : sParameterName[1];
        }
    }
};
hit_id = getUrlParameter('hit_id');
worker_id = getUrlParameter('worker_id');
assignment_id = getUrlParameter('assignment_id');
mode = getUrlParameter('mode');
participant_id = getUrlParameter('participant_id');

// stop people leaving the page
window.onbeforeunload = function() {
    return "Warning: the study is not yet finished. " +
    "Closing the window, refreshing the page or navigating elsewhere " +
    "might prevent you from finishing the experiment.";
};

// allow actions to leave the page
allow_exit = function() {
    window.onbeforeunload = function() {};
};

go_to_page = function(page) {
    window.location = "/" + page + "?participant_id=" + participant_id;
};

// go back to psiturk
submit_assignment = function() {
    reqwest({
        url: "/participant/" + participant_id,
        method: "get",
        type: 'json',
        success: function (resp) {
            mode = resp.participant.mode;
            hit_id = resp.participant.hit_id;
            assignment_id = resp.participant.assignment_id;
            worker_id = resp.participant.worker_id;
            reqwest({
                url: "/participant/" + participant_id + "/submit",
                method: 'post',
                //url: "/ad_address/" + mode + '/' + hit_id,
                //method: 'get',
                type: 'json',
                success: function (resp) {
                    allow_exit();
                    opener.location.reload(true);
                    //console.log(resp.address + "?uniqueId=" + worker_id + ":" + assignment_id);
                    //window.location = resp.address + "?uniqueId=" + worker_id + ":" + assignment_id;
                },
                error: function (err) {
                    console.log(err);
                    err_response = JSON.parse(err.response);
                    $('body').html(err_response.html);
                }
            });
        }
    });
    // reqwest({
    //     url: "/participant/" + participant_id + "/submit",
    //     method: "post",
    //     type: 'json',
    //     success: function (resp) {
    //         opener.location.reload(true);
    //         allow_exit();
    //         window.close();
    //     },
    //     error: function (err) {
    //         console.log(err);
    //         err_response = JSON.parse(err.response);
    //         $('body').html(err_response.html);
    //     }
    // });
    
};

// make a new participant
create_participant = function() {
    reqwest({
        url: "/participant/" + worker_id + '/' + hit_id + '/' + assignment_id + '/' + mode,
        method: 'post',
        type: 'json',
        success: function(resp) {
            participant_id = resp.participant.id;
        },
        error: function (err) {
            err_response = JSON.parse(err.response);
            $('body').html(err_response.html);
        }
    });
};
