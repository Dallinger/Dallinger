/*global require */
/*jshint esversion: 6 */

var dlgr = window.dlgr = (window.dlgr || {});

if (window.getUrlParameter === undefined) {
  var getUrlParameter = function getUrlParameter(sParam) {
      var sPageURL = decodeURIComponent(window.location.search.substring(1)),
          sURLVariables = sPageURL.split("&"),
          sParameterName,
          i;

      for (i = 0; i < sURLVariables.length; i++) {
          sParameterName = sURLVariables[i].split("=");

          if (sParameterName[0] === sParam) {
              return sParameterName[1] === undefined ? true : sParameterName[1];
          }
      }
  };
}

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
