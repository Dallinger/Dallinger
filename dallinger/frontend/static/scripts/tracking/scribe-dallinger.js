/*global module */
/*jshint esversion: 6 */

var ScribeDallingerTracker = function(config) {
  if (!(this instanceof ScribeDallingerTracker)) return new ScribeDallingerTracker(config);

  this.config = config;
};

ScribeDallingerTracker.prototype.tracker = function(info) {
  var config = this.config;
  var path = info.path;
  var value = info.value || {};
  var data = new FormData(); 
  if (config.base_url) {
    // Only track events
    if (path.indexOf('/events/') < 0) {
      return;
    }

    // Remove possible PII
    if (value.fingerprint) delete value.fingerprint;
    if (value.visitorId) delete value.visitorId;
    if (value.source && value.source.url && value.source.url.query) {
      if (value.source.url.query.worker_id) delete value.source.url.query.worker_id;
      if (value.source.url.query.workerId) delete value.source.url.query.workerId;
    }
    if (value.target && value.target.url && value.target.url.query) {
      if (value.target.url.query.worker_id) delete value.target.url.query.worker_id;
      if (value.target.url.query.workerId) delete value.target.url.query.workerId;
    }

    data.append('Event.1.EventType', 'TrackingEvent');
    if (config.participant_id) data.append('participant_id', config.participant_id);
    if (config.assignment_id) data.append('Event.1.AssignmentId', config.assignment_id);
    data.append('details', JSON.stringify(value));

    var xhr = new XMLHttpRequest();
    if (info.success) xhr.addEventListener("load", info.success);
    if (info.failure) {
      xhr.addEventListener("error", info.failure);
      xhr.addEventListener("abort", info.failure);
    }
    xhr.open('POST', config.base_url.replace(/\/$/, "") + '/notifications', true);
    xhr.send(data);
  } else {
    if(info.failure) setTimeout(info.failure, 0);
  }
};

module.exports.ScribeDallingerTracker = ScribeDallingerTracker;
