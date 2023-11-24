/*global module */
/*jshint esversion: 6 */

var dlgr = window.dlgr = (window.dlgr || {});

var ScribeDallingerTracker = function(config) {
  if (!(this instanceof ScribeDallingerTracker)) return new ScribeDallingerTracker(config);

  this.config = config;
  this.init();
};

ScribeDallingerTracker.prototype.tracker = function(info) {
  var config = this.config;
  var path = info.path;
  var value = this.stripPII(info.value || {});
  var data = new FormData();

  // Only track events
  if (path.indexOf('/events/') < 0) {
    return;
  }
  if (config.base_url) {
    data.append('info_type', 'TrackingEvent');
    data.append('details', JSON.stringify(value));

    var xhr = new XMLHttpRequest();
    if (info.success) xhr.addEventListener("load", info.success);
    if (info.failure) {
      xhr.addEventListener("error", info.failure);
      xhr.addEventListener("abort", info.failure);
    }
    xhr.open('POST', config.base_url.replace(/\/$/, "") + '/info/' + dlgr.node_id, true);
    xhr.send(data);
  } else if (info.failure) {
    setTimeout(info.failure, 0);
  }
};

ScribeDallingerTracker.prototype.stripPII = function(value) {
  // Remove possible PII
  delete value.fingerprint;
  delete value.visitorId;
  try {
    delete value.source.url.query.worker_id;
    delete value.source.url.query.workerId;
  } catch (e) {
    // Doesn't matter
  }
  try {
    delete value.target.url.query.worker_id;
    delete value.target.url.query.workerId;
  } catch (e) {
    // Doesn't matter
  }
  return value;
};

ScribeDallingerTracker.prototype.init = function() {
  var config = this.config;
  var getNodeDescriptor = function(node) {
    return {
      id:         node.id,
      selector:   'document',
      title:      node.title === '' ? undefined : node.title,
      data:       {}
    };
  };

  var trackSelectedText = function (e) {
    var text = '';
    if (window.getSelection) {
      text = window.getSelection();
    } else if (document.getSelection) {
      text = document.getSelection();
    } else if (document.selection) {
      text = document.selection.createRange().text;
    }
    text = text.toString();
    if (dlgr.tracker && text) {
      dlgr.tracker.track('text_selected', {
        target: getNodeDescriptor(e.target),
        selected: text
      });
    }
  };

  var trackScroll = function () {
    var doc = document.documentElement, body = document.body;
    var left = (doc && doc.scrollLeft || body && body.scrollLeft || 0);
    var top = (doc && doc.scrollTop  || body && body.scrollTop  || 0);
    dlgr.tracker.track('scroll', {
      target: getNodeDescriptor(doc || body),
      top: top,
      bottom: top + window.innerHeight,
      left: left,
      right: left + window.window.innerWidth
    });
  };

  var scrollHandler = function () {
    if (!dlgr.tracker) {
      return;
    }
    if (dlgr.scroll_timeout) {
      clearTimeout(dlgr.scroll_timeout);
    }
    dlgr.scroll_timeout = setTimeout(trackScroll, 500);
  };

  var trackContents = function () {
    if (!dlgr.tracker) {
      return;
    }
    var doc = document.documentElement || document.body;
    var content = doc.innerHTML;
    dlgr.tracker.track('page_contents', {
      target: getNodeDescriptor(doc),
      content: content
    });
  };

  if (config.trackSelection) {
    if (document.addEventListener) {
      document.addEventListener('mouseup', trackSelectedText);
    } else if (window.attachEvent)  {
      document.attachEvent('onmouseup', trackSelectedText);
    }
  }
  if (config.trackScroll) {
    if (window.addEventListener) {
      window.addEventListener('scroll', scrollHandler);
    } else if (window.attachEvent)  {
      window.attachEvent('onscroll', scrollHandler);
    }
  }
  if (config.trackContents) {
    setTimeout(trackContents, 100);
  }
};

module.exports.ScribeDallingerTracker = ScribeDallingerTracker;
