requirejs.config({
    paths: {
        'scribe-analytics': 'scribe-analytics.min'
    }
});
var tracker;

requirejs(['scribe-analytics', 'scribe-dallinger'],
function   (Scribe) {
    function getParticipantId() {
        var participant_id = getUrlParameter("participant_id");
        return participant_id === true ? null : participant_id;
    }

    function getAssignmentId() {
        var assignment_id = getUrlParameter("assignment_id");
        return assignment_id === true ? null : assignment_id;
    }

    function getBaseUrl() {
        return '/';
    }

    function configuredTracker() {
        return new ScribeDallingerTracker({
            participant_id: getParticipantId(),
            assignment_id: getAssignmentId(),
            base_url: getBaseUrl()
        });
    }

    if (!tracker) {
        tracker = new Scribe({
          tracker:    configuredTracker(), 
          trackPageViews:   true,
          trackClicks:      true,
          trackHashChanges: true,
          trackEngagement:  true,
          trackLinkClicks:  true,
          trackRedirects:   true,
          trackSubmissions: true
        });
    }
});
