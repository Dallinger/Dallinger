/*global require */
/*jshint esversion: 6 */

var dlgr = window.dlgr = (window.dlgr || {});

(function (require) {

  var Scribe = require('./scribe-analytics.min');
  var ScribeDallinger = require('./scribe-dallinger');

  function getParticipantId() {
    var participant_id = dlgr.participant_id;
    return participant_id === true ? null : participant_id;
  }

  function getNodeId() {
    return dlgr.node_id;
  }

  function getBaseUrl() {
    if (dlgr.experiment_url) return dlgr.experiment_url;
    return '/';
  }

  function configuredTracker() {
    return new ScribeDallinger.ScribeDallingerTracker({
      participant_id: getParticipantId(),
      node_id: getNodeId(),
      base_url: getBaseUrl(),
      trackScroll: true,
      trackSelection: true,
      trackContents: true
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

}(require));
