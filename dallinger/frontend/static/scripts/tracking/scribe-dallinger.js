var ScribeDallingerTracker = function(config) {
  if (!(this instanceof ScribeDallingerTracker)) return new ScribeDallingerTracker(config);

  this.config = config;
};

ScribeDallingerTracker.prototype.tracker = function(info) {
  var config = this.config;
  var path = info.path;
  var value = info.value;
  var data = new FormData(); 
   if (config.base_url) {
    // Only track events
    if (path.indexOf('/events/') < 0) {
      return;
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
