/*global getUrlParameter, require */
/*jshint esversion: 6 */

var dlgr = window.dlgr = (window.dlgr || {});

(function (getUrlParameter, require) {

  var Scribe = require('./scribe-analytics.min');
  var ScribeDallinger = require('./scribe-dallinger');

  function getParticipantId() {
      if (dlgr.participant_id) return dlgr.participant_id;
      var participant_id = getUrlParameter("participant_id");
      return participant_id === true ? null : participant_id;
  }

  function getAssignmentId() {
      var assignment_id = getUrlParameter("assignment_id");
      return assignment_id === true ? null : assignment_id;
  }

  function getBaseUrl() {
      if (dlgr.experiment_url) return dlgr.experiment_url;
      return '/';
  }

  function configuredTracker() {
      return new ScribeDallinger.ScribeDallingerTracker({
          participant_id: getParticipantId(),
          assignment_id: getAssignmentId(),
          base_url: getBaseUrl()
      });
  }

  if (!dlgr.tracker) {
      dlgr.tracker = new Scribe({
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

})(getUrlParameter, require);
