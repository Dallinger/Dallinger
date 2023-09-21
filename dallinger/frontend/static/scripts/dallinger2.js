/*globals Spinner, Fingerprint2, ReconnectingWebSocket, reqwest, store */
/**
 * @file Defines a global ``dallinger`` object which provides various methods for interacting with dallinger experiments.
 */

if (window.Dallinger !== undefined) {
  alert(
    'This page has loaded both dallinger.js and dallinger2.js at the same time, ' +
    'which is not supported. It is recommended to use dallinger2.js ' +
    'for experiments being actively developed, and dallinger.js only ' +
    'for backwards compatibility of existing experiments.'
  );
}
var dallinger = (function () {
  /**
   * @namespace
   * @alias dallinger
   */
  var dlgr = {};

  dlgr.skip_experiment = false;

  /**
   * Returns a url query string value given the parameter name.
   *
   * @example
   * // Given a url with ``?param1=aaa&param2``, the following returns "aaa"
   * dallinger.getUrlParameter("param1");
   * // this returns true
   * dallinger.getUrlParameter("param2");
   * // and this returns null
   * dallinger.getUrlParameter("param3");
   *
   * @param {string} sParam - name of url parameter
   * @returns {string|boolean} the parameter value if available; ``true`` if parameter is in the url but has no value;
   */
  dlgr.getUrlParameter = function getUrlParameter(sParam) {
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

  dlgr.storage = {
    available: typeof store !== 'undefined',
    _storage: store,
    set: function (key, value) {
      if (this._isUndefined(value)) {
        return;
      }
      this._storage.set(key, value);
    },
    get: function (key) {
      return this._storage.get(key);
    },
    all: function () {
      return this._storage.getAll();
    },
    _isUndefined: function (value) {
      return typeof value === 'undefined';
    }
  };

  /**
   * ``dallinger.identity`` provides information about the participant.
   * It has the following string properties:
   *
   * ``recruiter``     - Type of recruiter
   *
   * ``hitId``         - MTurk HIT Id
   *
   * ``workerId``      - MTurk Worker Id
   *
   * ``assignmentId``  - MTurk Assignment Id
   *
   * ``uniqueId``      - MTurk Worker Id and Assignment Id
   *
   * ``mode``          - Dallinger experiment mode
   *
   * ``participantId`` - Dallinger participant Id
   *
   * @namespace
   */
  dlgr.identity = {
    get recruiter() { return dlgr.storage.get("recruiter"); },
    set recruiter(value) { dlgr.storage.set("recruiter", value); },
    get hitId() { return  dlgr.storage.get("hit_id"); },
    set hitId(value) {  dlgr.storage.set("hit_id", value); },
    get workerId() { return  dlgr.storage.get('worker_id'); },
    set workerId(value) {  dlgr.storage.set('worker_id', value); },
    get assignmentId() { return  dlgr.storage.get('assignment_id'); },
    set assignmentId(value) {  dlgr.storage.set('assignment_id', value); },
    get uniqueId() { return  dlgr.storage.get('unique_id'); },
    set uniqueId(value) {  dlgr.storage.set('unique_id', value); },
    get mode() { return  dlgr.storage.get('mode'); },
    set mode(value) {  dlgr.storage.set('mode', value); },
    get participantId() { return dlgr.storage.get('participant_id'); },
    set participantId(value) { dlgr.storage.set('participant_id', value); },
    get fingerprintHash() { return dlgr.storage.get('fingerprint_hash'); },
    set fingerprintHash(value) { dlgr.storage.set('fingerprint_hash', value);},
    get entryInformation() { return dlgr.storage.get('entry_information'); },
    set entryInformation(value) { dlgr.storage.set('entry_information', value);},

    initialize: function () {
      this.recruiter = dlgr.getUrlParameter('recruiter');
      this.hitId = dlgr.getUrlParameter('hitId');
      this.workerId = dlgr.getUrlParameter('workerId');
      this.assignmentId = dlgr.getUrlParameter('assignmentId');
      this.uniqueId = dlgr.getUrlParameter('workerId') + ":" + dlgr.getUrlParameter('assignmentId');
      this.mode = dlgr.getUrlParameter('mode');
      // Store all url parameters as entry information.
      // This won't work in IE, but should work in Edge.
      var entry_info = {
        assignmentId: this.assignmentId,
        hitId: this.hitId,
        workerId: this.workerId,
        mode: this.mode
      };
      var query_params = new URLSearchParams(location.search);
      for (const [k, v] of query_params) {
        entry_info[k] = v;
      }
      this.entryInformation = entry_info;
      if (this.entryInformation.mode) {
        delete this.entryInformation.mode;
      }
      var _self = this;
      new Fingerprint2().get(function(result){
        _self.fingerprintHash = result;
      });
    }
  };

  dlgr.BusyForm = (function () {
    /* Loads a spinner as a visual cue that something is happening
       and disables any jQuery objects passed to freeze(). */

    var defaults = {
      spinnerSettings: {scale: 1.5}, // See http://spin.js.org/ for all settings
      spinnerID: 'spinner'  // ID for HTML element where spinner will be inserted
    };

    var BusyForm = function (options) {
      if (!(this instanceof BusyForm)) {
        return new BusyForm(options);
      }
      var settings = $.extend(true, {}, defaults, options);
      this.spinner = new Spinner(settings.spinnerSettings);
      this.target = document.getElementById(settings.spinnerID);
      if (this.target === null) {
        throw new Error(
          'Target HTML element for spinner with ID "' + settings.spinnerID +
          '" does not exist.');
      }
      this.$elements = [];
    };

    BusyForm.prototype.freeze = function ($elements) {
      this.$elements = $elements;
      this.$elements.forEach(function ($element) {
        $element.attr("disabled", true);
      });
      this.spinner.spin(this.target);
    };

    BusyForm.prototype.unfreeze = function () {
      this.$elements.forEach(function ($element) {
        $element.attr("disabled", false);
      });
      this.spinner.stop();
      this.$elements = [];
    };

    return BusyForm;
  }());

  dlgr.AjaxRejection = (function () {
    // Capture information related to a rejected dallinger.ajax() call.

    var _responseHTML = function (response) {
      var parsed;
      try {
        parsed = JSON.parse(response);
      } catch (error) {
        console.log('Error response not parseable.');
        parsed = {};
      }
      if (parsed.hasOwnProperty('html')) {
        return parsed.html;
      }
      return '';
    };

    var AjaxRejection = function (options) {
      if (!(this instanceof AjaxRejection)) {
        return new AjaxRejection(options);
      }

      this.route = options.route;
      this.method = options.method;
      this.data = options.data || {};
      this.error = options.error;
      this.status = options.error.status;
      this.html = _responseHTML(this.error.response);
      this.requestJSON = JSON.stringify({
        'route': this.route,
        'data': JSON.stringify(this.data),
        'method': this.method
      });
    };

    return AjaxRejection;
  }());

  // stop people leaving the page, but only if desired by experiment
  dlgr.allowExitOnce = false;
  dlgr.preventExit = false;
  window.addEventListener('beforeunload', function(e) {
    if (dlgr.preventExit && !dlgr.allowExitOnce) {
      var returnValue = "Warning: the study is not yet finished. " +
        "Closing the window, refreshing the page or navigating elsewhere " +
        "might prevent you from finishing the experiment.";
      e.returnValue = returnValue;
      return returnValue;
    } else {
      dlgr.allowExitOnce = false;
      return undefined;
    }
  });
  // allow actions to leave the page
  dlgr.allowExit = function() {
    dlgr.allowExitOnce = true;
  };

  /**
   * Advance the participant to a given html page;
   * the ``participant_id`` will be included in the url query string.
   *
   * @param {string} page - Name of page to load, the .html extension
   * should not be included.
   */
  dlgr.goToPage = function(page) {
    if (dlgr.identity.participantId) {
      window.location = "/" + page + "?participant_id=" + dlgr.identity.participantId;
    } else {
      window.location = "/" + page + '?assignmentId=' + dlgr.identity.assignmentId + "&hitId=" + dlgr.identity.hitId + "&workerId=" + dlgr.identity.workerId + "&mode=" + dlgr.identity.mode;
    }
  };

  var add_hidden_input = function ($form, name, val) {
    if (val) {
      $form.append($('<input>').attr('type', 'hidden').attr('name', name).val(val));
    }
  };

  // AJAX helpers
  var ajax = function (method, route, data) {
    var deferred = $.Deferred();
    var options = {
      url: route,
      method: method,
      type: 'json',
      success: function (resp) { deferred.resolve(resp); },
      error: function (err) {
        console.log(err);
        var rejection = dlgr.AjaxRejection(
          {'route': route, 'method': method, 'data': data, 'error': err}
        );
        deferred.reject(rejection);
      }
    };
    if (data !== undefined) {
      options.data = data;
    }
    reqwest(options);
    return deferred;
  };

  /**
   * Convenience method for making an AJAX ``GET`` request to a specified
   * route. Any callbacks provided to the `done()` method of the returned
   * `Deferred` object will be passed the JSON object returned by the the
   * API route (referred to as `data` below). Any callbacks provided to the
   * `fail()` method of the returned `Deferred` object will be passed an
   * instance of `AjaxRejection`, see :ref:`deferreds-label`.
   *
   * @example
   * var response = dallinger.get('/participant/1');
   * // Wait for response and handle data
   * response.done(function (data) {...});
   *
   * @param {string} route - Experiment route, e.g. ``/info/$nodeId``
   * @param {object} [data] - Optional data to include in request
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.get = function (route, data) {
    return ajax('get', route, data);
  };

  /**
   * Convenience method for making an AJAX ``POST`` request to a specified
   * route.  Any callbacks provided to the `done()` method of the returned
   * `Deferred` object will be passed the JSON object returned by the the
   * API route (referred to as `data` below). Any callbacks provided to the
   * `fail()` method of the returned `Deferred` object will be passed an
   * instance of `AjaxRejection`, see :ref:`deferreds-label`.
   *
   * @example
   * var response = dallinger.post('/info/1', {details: {a: 1}});
   * // Wait for response and handle data or failure
   * response.done(function (data) {...}).fail(function (rejection) {...});
   *
   * @param {string} route - Experiment route, e.g. ``/info/$nodeId``
   * @param {object} [data] - Optional data to include in request
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.post = function (route, data) {
    return ajax('post', route, data);
  };

  /**
   * Handles experiment errors by requesting feedback from the participant and
   * attempts to complete the experiment (and compensate participants).
   *
   * @example
   * // Let dallinger handle the error
   * dallinger.createAgent().fail(dallinger.error);
   *
   * // Custom handling, then request feedback and complete if possible
   * dallinger.getInfo(info).fail(function (rejection) {
   *  ... handle rejection data ...
   *  dallinger.error(rejection);
   * });
   *
   * @param {dallinger.AjaxRejection} rejection - information about the AJAX error.
   */
  dlgr.error = function (rejection) {
    // Render an error form for a rejected deferred returned by an ajax() call.
    var hit_params = {
          'recruiter': dlgr.identity.recruiter,
          'mode': dlgr.identity.mode,
          'hit_id': dlgr.identity.hitId,
          'worker_id': dlgr.identity.workerId,
          'assignment_id': dlgr.identity.assignmentId,
          'fingerprint_hash': dlgr.identity.fingerprintHash,
        },
        $form;

    console.log("Calling dallinger.error()");

    if (rejection.html) {
      $('html').html(rejection.html);
      $form = $('form#error-response');
    } else {
      $form = $('<form>').attr('action', '/error-page').attr('method', 'POST');
      $('body').append($form);
    }
    if (rejection.data.participant_id) {
      add_hidden_input($form, 'participant_id', rejection.data.participant_id);
    }
    add_hidden_input($form, 'request_data', rejection.requestJSON);
    for (var prop in hit_params) {
      if (hit_params.hasOwnProperty(prop)) add_hidden_input($form, prop, hit_params[prop]);
    }
    if (!rejection.html) {
      $form.submit();
    }
  };

  /**
   * Notify the experiment that the participant's assignment is complete.
   * Performs a ``POST`` request to the experiment's ``/worker_complete`` route,
   * then redirects the main/parent window to the ``/recruiter-exit`` route and
   * closes the secondary window in which the experiment ran.
   *
   * @example
   * // Mark the assignment complete and perform a custom function when successful
   * result = dallinger.submitAssignment();
   * result.done(function (data) {... handle ``data.status`` ...}).fail(
   *     dallinger.error
   * );
   *
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.submitAssignment = function() {
    var deferred = $.Deferred(),
        participantId = dlgr.identity.participantId,
        exitRoute = "/recruiter-exit?participant_id=" + participantId;

    dlgr.post('/worker_complete', {
        'participant_id': participantId
    }).done(function () {
      deferred.resolve();
      dlgr.allowExit();

      let openedFromDashboard;
      try {
        openedFromDashboard = window.opener && window.opener.location.pathname.startsWith("/dashboard");
      } catch (error) {
        // If the parent window was from a different origin (e.g. Prolific) then we see an error like this:
        // Uncaught DOMException: Blocked a frame with origin XXX from accessing a cross-origin frame.
        // We catch and ignore this error.
        openedFromDashboard = false;
      }

      if (window.opener && !openedFromDashboard) {
        // If the parent window is still around, redirect it to the exit route
        // and close the secondary window (this one) that held the main experiment:
        window.opener.location = exitRoute;
        window.close();
      } else {
        // We're the only window, so show the exit route here:
        window.location = exitRoute;
      }
    }).fail(function (err) {
      deferred.reject(err);
    });

    return deferred;
  };

  /**
   * Create a new experiment ``Participant`` by making a ``POST`` request to
   * the experiment ``/participant/`` route. If the experiment requires a
   * quorum, the response will not resolve until the quorum is met. If the
   * participant is requested after the quorum has already been reached, the
   * ``dallinger.skip_experiment`` flag will be set and the experiment will
   * be skipped.
   *
   * This method is called automatically by the default waiting room page.
   *
   * @example
   * // Create a new participant using entry information from dallinger.identity
   * result = dallinger.createParticipant();
   * result.done(function () {... handle ``data.status`` ...});
   *
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.createParticipant = function() {
    var url = "/participant";
    var data = {};
    var deferred = $.Deferred();
    if (dlgr.identity.entryInformation) {
      data = dlgr.identity.entryInformation;
      if (dlgr.identity.fingerprintHash) {
        data.fingerprint_hash = dlgr.identity.fingerprintHash;
      }
    } else {
      url += "/" + dlgr.identity.workerId + "/" + dlgr.identity.hitId +
            "/" + dlgr.identity.assignmentId + "/" + dlgr.identity.mode + "?fingerprint_hash=" +
            (dlgr.identity.fingerprintHash) + '&recruiter=' + dlgr.identity.recruiter;
    }

    if (dlgr.identity.participantId !== undefined && dlgr.identity.participantId !== 'undefined') {
      deferred.resolve();
    } else {
      $(function () {
        $('.btn-success').prop('disabled', true);
        dlgr.post(url, data).done(function (resp) {
          console.log(resp);
          $('.btn-success').prop('disabled', false);
          dlgr.identity.participantId = resp.participant.id;
          dlgr.identity.assignmentId = resp.participant.assignment_id;
          dlgr.identity.uniqueId = resp.participant.unique_id;
          dlgr.identity.workerId = resp.participant.worker_id;
          dlgr.identity.hitId = resp.participant.hit_id;
          if (! resp.quorum) {  // We're not using a waiting room.
            deferred.resolve();
            return;
          }

          // We've got a waiting room, so run waiting room checks...
          if (resp.quorum.overrecruited) {
            // If we're overrecruited, no need to check anything else.
            dlgr.skip_experiment = true;
            deferred.resolve();
            return;
          }

          if (resp.quorum.n < resp.quorum.q) {
            // wait for quorum, then resolve
            dlgr.updateProgressBar(resp.quorum.n, resp.quorum.q);
            dlgr.waitForQuorum().done(function () {
              deferred.resolve();
            });
          } else {
            // last through the door; resolve immediately
            deferred.resolve();
          }
        });
      });
    }
    return deferred;
  };

  /**
   * Load an existing `Participant` into the dlgr.identity by making a ``POST``
   * request to the experiment `/participant` route with some ``assignment_info``
   * which can be a scalar ``assignment_id`` or an object with ``entry_information``
   * parameters
   *
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.loadParticipant = function(assignment_info) {
    var data,
        deferred = $.Deferred(),
        url = '/load-participant';

    if (typeof assignment_info === "object") {
      data = assignment_info;
      dlgr.identity.entryInformation = assignment_info;
    } else {
      data = {assignment_id: assignment_info}
    }

    if (dlgr.identity.participantId !== undefined && dlgr.identity.participantId !== 'undefined') {
      deferred.resolve();
    } else {
      $(function () {
        $('.btn-success').prop('disabled', true);
        dlgr.post(url, data).done(function (resp) {
          console.log(resp);
          $('.btn-success').prop('disabled', false);
          dlgr.identity.participantId = resp.participant.id;
          dlgr.identity.recruiter = resp.participant.recruiter_id;
          dlgr.identity.hitId = resp.participant.hit_id;
          dlgr.identity.workerId = resp.participant.worker_id;
          dlgr.identity.assignmentId = resp.participant.assignment_id || data.assignment_id;
          dlgr.identity.mode = resp.participant.mode;
          dlgr.identity.fingerprintHash = resp.participant.fingerprint_hash;
          deferred.resolve();
        });
      });
    }
    return deferred;
  };

  /**
   * Creates a new experiment `Node` for the current partcipant.
   *
   * @example
   * var response = dallinger.createAgent();
   * // Wait for response
   * response.done(function (data) {... handle data.node ...});
   *
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.createAgent = function () {
    return dlgr.post('/node/' + dallinger.identity.participantId);
  };

  /**
   * Creates a new `Info` object in the experiment database.
   *
   * @example
   * var response = dallinger.createInfo(1, {details: {a: 1}});
   * // Wait for response
   * response.done(function (data) {... handle data.info ...});
   *
   * @param {number} nodeId - The id of the participant's experiment node
   * @param {Object} data - Experimental data (see :class:`~dallinger.models.Info`)
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.createInfo = function (nodeId, data) {
    return dlgr.post('/info/' + nodeId, data);
  };

  /**
   * Returns a public property value for the experiment.
   *
   * @example
   * var response = dallinger.getExperimentProperty("propname");
   * // Wait for response
   * response.done(function (data) {... handle e.g. data.propname ...});
   *
   * @param {string} prop - The experiment property to lookup
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.getExperimentProperty = function (prop) {
    return dlgr.get('/experiment/' + prop);
  };

  /**
   * Get a specific `Info` object from the experiment database.
   *
   * @example
   * var response = dallinger.getInfo(1, 1);
   * // Wait for response
   * response.done(function (data) {... handle data.info ...});
   *
   * @param {number} nodeId - The id of an experiment node
   * @param {number} infoId - The id of the Info object to be retrieved
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.getInfo = function (nodeId, infoId) {
    return dlgr.get('/info/' + nodeId + '/' + infoId);
  };

  /**
   * Get all `Info` objects for the specified node.
   *
   * @example
   * var response = dallinger.getInfos(1, 1);
   * // Wait for response
   * response.done(function (data) {... handle data.infos ...});
   *
   * @param {number} nodeId - The id of an experiment node.
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.getInfos = function (nodeId) {
    return dlgr.get('/node/' + nodeId + '/infos');
  };

  /**
   * Get all the `Info` objects a node has been sent and has received.
   *
   * @example
   * var response = dallinger.getReceivedInfostInfos(1);
   * // Wait for response
   * response.done(function (data) {... handle data.infos ...});
   *
   * @param {number} nodeId - The id of an experiment node.
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.getReceivedInfos = function (nodeId) {
    return dlgr.get('/node/' + nodeId + '/received_infos');
  };

  /**
   * Get all `Transmission` objects connected to a node.
   *
   * @example
   * var response = dallinger.getTransmissions(1, {direction: "to", status: "all"});
   * // Wait for response
   * response.done(function (data) {... handle data.transmissions ...});
   *
   * @param {number} nodeId - The id of an experiment node.
   * @param {Object} data - Additional parameters, specifically ``direction`` (to/from/all) and ``status`` (all/pending/received).
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.getTransmissions = function (nodeId, data) {
    return dlgr.get('/node/' + nodeId + '/transmissions', data);
  };

  /**
   * Submits a `Question` object to the experiment server.
   * This method is called automatically from the default questionnaire page.
   *
   * @param {string} [name=questionnaire] - optional questionnaire name
   */
  dlgr.submitQuestionnaire = function (name) {
    var $inputs = $("form :input");
    var $button = $("button#submit-questionnaire");
    var spinner = dlgr.BusyForm();
    var formDict = {};
    $.each($inputs, function(key, input) {
      if (input.name !== "") {
        formDict[input.name] = $(input).val();
      }
    });

    xhr = dlgr.post('/question/' + dlgr.identity.participantId, {
      question: name || "questionnaire",
      number: 1,
      response: JSON.stringify(formDict)
    });
    spinner.freeze([$inputs, $button]);
    xhr.done(function () {
      dlgr.submitAssignment().done(function () {
       spinner.unfreeze();
      }).fail(function (rejection) {
        dlgr.error(rejection);
      });
    }).fail(function (rejection) {
      dlgr.error(rejection);
    });
  };

  /**
   * Waits for a WebSocket message indicating that quorum has been reached.
   *
   * This method is called automatically within `createParticipant()` and the
   * default waiting room page.
   *
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   */
  dlgr.waitForQuorum = function () {
    var ws_scheme = (window.location.protocol === "https:") ? 'wss://' : 'ws://';
    var socket = new ReconnectingWebSocket(ws_scheme + location.host + "/chat?channel=quorum&worker_id=" + dlgr.identity.workerId + '&participant_id=' + dlgr.identity.participantId);
    var deferred = $.Deferred();
    socket.onmessage = function (msg) {
      if (msg.data.indexOf('quorum:') !== 0) { return; }
      var data = JSON.parse(msg.data.substring(7));
      var n = data.n;
      var quorum = data.q;
      dlgr.updateProgressBar(n, quorum);
      if (n === quorum) {
        deferred.resolve();
      }
    };
    return deferred;
  };

  dlgr.updateProgressBar = function (value, total) {
    var percent = Math.round((value / total) * 100.0) + '%';
    $("#waiting-progress-bar").css("width", percent);
    $("#progress-percentage").text(percent);
  };

  dlgr.missingFingerprint = function () {
    if (window.Fingerprint2 === undefined) {
      return true;
    }
    return false;
  };

  /**
   * Determine if the user has an ad blocker installed. If an ad blocker is detected
   * the callback will be executed asynchronously after a small delay.
   *
   * This method is called automatically from the experiment default template.
   *
   * @param {function} callback - a function, with no arguments, to call if an ad blocker is running.
   */
  dlgr.hasAdBlocker = function (callback) {
    var test = document.createElement('div');
    test.innerHTML = '&nbsp;';
    test.className = 'adsbox';
    document.body.appendChild(test);
    window.setTimeout(function() {
      if (test.offsetHeight === 0) {
        return callback();
      }
      test.remove();
    }, 100);
  };

  var _initialize = function () {
    if (dlgr.missingFingerprint()) {
      window.alert(
        'An ad blocker is preventing this experiment from ' +
        'loading. Please disable it and reload the page.'
      );
      return;
    }
    dlgr.identity.initialize();
  };

  _initialize();

  return dlgr;
}());


try {
  module.exports.dallinger = dallinger;
} catch (err) {
  // We aren't being loaded from a node context, no need to export
}
