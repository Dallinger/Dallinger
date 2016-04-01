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
return_to_psiturk_server = function() {
    reqwest({
        url: "/ad_address/" + mode + '/' + hit_id,
        method: 'get',
        type: 'json',
        success: function (resp) {
            console.log(resp.address);
            allow_exit();
            window.location = resp.address + "?hit_id=" + hit_id + "&assignment_id=" + assignment_id + "&worker_id=" + worker_id + "&mode=" + mode;
        },
        error: function (err) {
            console.log(err);
            err_response = JSON.parse(err.response);
            $('body').html(err_response.html);
        }
    });
};

// make a new participant
create_participant = function() {
    reqwest({
        url: "/participant/" + worker_id + '/' + hit_id + '/' + assignment_id,
        method: 'post',
        type: 'json'
    });
};