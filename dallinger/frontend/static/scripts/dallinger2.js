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

  /**
   * Information about a rejected ``dallinger.get`` / ``dallinger.post`` call.
   *
   * Properties:
   *
   * ``route``      - Requested experiment route
   *
   * ``method``     - HTTP method used for the request
   *
   * ``data``       - Data that was sent with the request
   *
   * ``error``      - Underlying transport error object
   *
   * ``status``     - HTTP status code from the failed request
   *
   * ``response``   - Parsed JSON object body from the server, ``{}`` when the
   *                  body is missing, unparseable, or not a JSON object
   *
   * ``html``       - Rendered error HTML from the server response, if present
   *
   * ``errorCode``  - Optional machine-readable ``error_code`` from the server
   *                  JSON body (for example ``participant_not_found`` or
   *                  ``assignment_id_missing``)
   *
   * ``requestJSON`` - Serialized request details for error reporting
   *
   * @constructor
   * @param {Object} options - Rejection details from the AJAX helper
   */
  dlgr.AjaxRejection = (function () {
    var _responseData = function (response) {
      var parsed;
      try {
        parsed = JSON.parse(response);
      } catch (error) {
        console.log('Error response not parseable.');
        return {};
      }
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return {};
      }
      return parsed;
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
      this.response = _responseData(this.error.response);
      this.html = this.response.html || '';
      this.errorCode = this.response.error_code;
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
          dlgr.identity.participantId = resp.participant.id;
          dlgr.identity.assignmentId = resp.participant.assignment_id;
          dlgr.identity.uniqueId = resp.participant.unique_id;
          dlgr.identity.workerId = resp.participant.worker_id;
          dlgr.identity.hitId = resp.participant.hit_id;
          $('.btn-success').prop('disabled', false);
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
          dlgr.identity.participantId = resp.participant.id;
          dlgr.identity.recruiter = resp.participant.recruiter_id;
          dlgr.identity.hitId = resp.participant.hit_id;
          dlgr.identity.workerId = resp.participant.worker_id;
          dlgr.identity.assignmentId = resp.participant.assignment_id || data.assignment_id;
          dlgr.identity.mode = resp.participant.mode;
          dlgr.identity.fingerprintHash = resp.participant.fingerprint_hash;
          $('.btn-success').prop('disabled', false);
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
   * The close code Dallinger sends when it refuses a connection outright,
   * for example, when the participant_id is invalid.
   * The browser's ReconnectingWebSocket should not retry on this code.
   */
  dlgr.WEBSOCKET_REFUSED = 1008;

  /**
   * Stop a ReconnectingWebSocket retrying a connection the server refused.
   *
   * `ReconnectingWebSocket` reconnects after every close and reports the close
   * code on its `connecting` event rather than on `close`, so a refusal is
   * otherwise indistinguishable from a dropped network connection and repeats
   * forever.
   *
   * The socket is left in the `CLOSED` state, so code that polls
   * `readyState` can tell a refusal from a reconnect in progress.
   *
   * @param {ReconnectingWebSocket} socket the socket to watch
   * @param {function} [callback] called with the close code and reason when
   *   the connection is refused
   * @returns {ReconnectingWebSocket} the socket that was passed in
   */
  dlgr.stopReconnectingIfRefused = function (socket, callback) {
    socket.addEventListener("connecting", function (event) {
      if (event.code !== dlgr.WEBSOCKET_REFUSED) { return; }
      // ReconnectingWebSocket schedules a reconnect timer on every close, and
      // exposes no public API to cancel it. The timer calls this.open() when it
      // fires. Replacing open() with a no-op on this instance is the only way to
      // cancel the retry from outside, and since open() is an "own property" it applies
      // only to this socket instance.
      socket.open = function () {};
      socket.close();
      // `close()` reaches CLOSED only through a live socket's onclose, and
      // ReconnectingWebSocket has already dropped its reference to that socket
      // before it fires `connecting`. Without this the socket would report
      // CONNECTING forever.
      socket.readyState = WebSocket.CLOSED;
      if (callback) { callback(event.code, event.reason); }
    });
    return socket;
  };

  /**
   * The channel on which directed messages, sent with the experiment's
   * ``publish_to_participants`` method, arrive. It is reserved for
   * Dallinger's own use, so a client may neither subscribe nor send to it.
   */
  dlgr.DIRECT_CHANNEL = "dallinger_direct";

  /**
   * The channel on which a page in a real-time session measures its clock
   * against the server's. It is reserved for Dallinger's own use.
   */
  dlgr.TIME_CHANNEL = "dallinger_time";

  /**
   * The channel on which a page in a real-time session receives its views,
   * and learns that the session has ended. It is reserved for Dallinger's own
   * use.
   */
  dlgr.REALTIME_SESSION_CHANNEL = "dallinger_realtime_session";

  var RESERVED_CHANNELS = [
    "dallinger_control",
    dlgr.DIRECT_CHANNEL,
    dlgr.REALTIME_SESSION_CHANNEL,
    dlgr.TIME_CHANNEL,
  ];

  /**
   * A value identifying this page load. Sockets opened with
   * ``dallinger.openChatSocket`` or ``dallinger.openExperimentSocket`` send it
   * as their ``scope`` unless they are given another, so an experiment which
   * replies with the ``scope`` its handler was given reaches the page that
   * sent the message, and not an earlier page whose socket is still open.
   */
  dlgr.pageScope = Math.random().toString(36).substring(2) + Date.now().toString(36);

  // Sessions count a page's messages by its scope, so the page's sockets
  // share one count.
  var lastMessageNumber = 0;

  var socketUrl = function (route, params) {
    var scheme = (window.location.protocol === "https:") ? 'wss://' : 'ws://';
    var query = new URLSearchParams();
    Object.keys(params).forEach(function (name) {
      var value = params[name];
      if (value !== undefined && value !== null && value !== '') {
        query.append(name, value);
      }
    });
    var search = query.toString();
    return scheme + location.host + route + (search ? '?' + search : '');
  };

  var parsePayload = function (payload) {
    try {
      return JSON.parse(payload);
    } catch (err) {
      return payload;
    }
  };

  // The server splits each message at its first colon to find the channel.
  var checkSendChannel = function (channel) {
    if (typeof channel !== 'string' || !channel || channel.indexOf(':') !== -1) {
      throw new Error("A channel name must be a non-empty string without a colon, not " + JSON.stringify(channel) + ".");
    }
    if (RESERVED_CHANNELS.indexOf(channel) !== -1) {
      throw new Error('The "' + channel + '" channel is reserved for Dallinger\'s own use.');
    }
  };

  // The frames dallinger.realtime.delivery sends a page about its session.
  var SESSION_FRAMES = ["realtime_view", "realtime_ended", "realtime_saved"];

  // Seconds since 1970, from the clock that doesn't jump when the computer's
  // clock is set.
  var browserTime = function () {
    return (performance.timeOrigin + performance.now()) / 1000;
  };

  /**
   * A connection to one of the experiment server's WebSocket routes, created
   * with ``dallinger.openChatSocket`` or ``dallinger.openExperimentSocket``.
   *
   * The connection is a ``ReconnectingWebSocket``, available as the ``raw``
   * property, which reconnects with a growing delay whenever it is dropped.
   * A connection the server refuses is not retried.
   *
   * A connection opened with a ``session`` joins that real-time session each
   * time it opens, and the session sends the page a view straight away, or
   * its ending if it has ended. See ``onView`` and ``onEnded``.
   *
   * @constructor
   * @param {string} route - Path of the WebSocket route
   * @param {Object} [options] - See ``dallinger.openChatSocket``
   */
  dlgr.Socket = function (route, options) {
    var self = this;
    options = options || {};
    this.channel = options.channel || null;
    if (RESERVED_CHANNELS.indexOf(this.channel) !== -1) {
      throw new Error('The "' + this.channel + '" channel is reserved for Dallinger\'s own use.');
    }
    this.participantId = dlgr.identity.participantId;
    this.scope = options.scope === undefined ? dlgr.pageScope : options.scope;
    this.session = options.session == null ? null : options.session;
    this.gameChannel = options.gameChannel == null ? null : options.gameChannel;
    if ((this.session === null) !== (this.gameChannel === null)) {
      throw new Error("A socket that joins a session needs both the session and its game type's gameChannel.");
    }
    if (this.session !== null) {
      if (!/^[0-9]+$/.test(String(this.session))) {
        throw new Error("A session id is a whole number, not " + JSON.stringify(this.session) + ".");
      }
      this.session = Number(this.session);
      checkSendChannel(this.gameChannel);
      if (this.participantId == null) {
        throw new Error("A socket that joins a session needs a participant id.");
      }
    }
    this._pending = [];
    this._closed = false;
    this._callbacks = {
      broadcast: [], direct: [], open: [], refused: [],
      view: [], rejected: [], ended: [], saved: []
    };
    this._connection = 0;
    // Messages sent on the game channel that no view has acknowledged, each
    // with the connection it went out on, or null while it is held.
    this._unacknowledged = [];
    this._view = null;
    this._reportedRejections = {};
    this._ended = false;
    this._saved = this.session === null ? null : $.Deferred();
    this.raw = new ReconnectingWebSocket(socketUrl(route, {
      channel: this.channel,
      worker_id: dlgr.identity.workerId,
      participant_id: this.participantId,
      scope: this.scope,
      session: this.session
    }));
    this.raw.addEventListener("open", function (event) {
      var pending = self._pending;
      self._connection += 1;
      self._pending = [];
      pending.forEach(function (frame) { self.raw.send(frame); });
      self._unacknowledged.forEach(function (message) {
        if (message.connection === null) { message.connection = self._connection; }
      });
      self._notify("open", [event]);
    });
    this.raw.addEventListener("message", function (event) {
      self._receive(event.data);
    });
    dlgr.stopReconnectingIfRefused(this.raw, function (code, reason) {
      self._stop(code, reason);
      if (!self._callbacks.refused.length) {
        console.error("The server refused a WebSocket connection to " + route + ": " + reason);
      }
      self._notify("refused", [code, reason]);
    });
  };

  // Ends the socket for good, discarding held messages, with the close code
  // and reason of a refusal.
  dlgr.Socket.prototype._stop = function (code, reason) {
    this._closed = true;
    this._pending = [];
    this._unacknowledged = this._unacknowledged.filter(function (message) {
      return message.connection !== null;
    });
    if (this._saved !== null) { this._saved.reject(code, reason); }
  };

  dlgr.Socket.prototype._notify = function (kind, args) {
    this._callbacks[kind].forEach(function (callback) {
      callback.apply(null, args);
    });
  };

  dlgr.Socket.prototype._receive = function (frame) {
    var prefix, kind;
    // The subscribed channel is matched first and in full, so that a channel
    // name containing a colon is not mistaken for a shorter one.
    if (this.channel !== null && frame.indexOf(this.channel + ':') === 0) {
      prefix = this.channel + ':';
      kind = "broadcast";
    } else if (frame.indexOf(dlgr.DIRECT_CHANNEL + ':') === 0) {
      prefix = dlgr.DIRECT_CHANNEL + ':';
      kind = "direct";
    } else if (frame.indexOf(dlgr.REALTIME_SESSION_CHANNEL + ':') === 0) {
      // Every socket of the participant gets these, whatever its session.
      var data = parsePayload(frame.substring(dlgr.REALTIME_SESSION_CHANNEL.length + 1));
      if (this._isSessionFrame(data)) { this._receiveSessionFrame(data); }
      return;
    } else {
      return;
    }
    var payload = frame.substring(prefix.length);
    this._notify(kind, [parsePayload(payload), payload]);
  };

  dlgr.Socket.prototype._isSessionFrame = function (data) {
    return data != null && data.session_id === this.session &&
      SESSION_FRAMES.indexOf(data.type) !== -1;
  };

  dlgr.Socket.prototype._receiveSessionFrame = function (data) {
    if (data.type === "realtime_view") {
      this._receiveView(data.view);
      return;
    }
    this._end(data.reason, data.view);
    if (data.type === "realtime_saved" && this._saved.state() === "pending") {
      this._notify("saved", [data]);
      this._saved.resolve(data);
    }
  };

  dlgr.Socket.prototype._receiveView = function (envelope) {
    var self = this;
    // A view that arrives late still reports its rejections.
    var rejections = envelope.rejected.filter(function (rejection) {
      if (self._reportedRejections[rejection.number]) { return false; }
      self._reportedRejections[rejection.number] = true;
      return true;
    });
    var newest = this._view === null || envelope.number > this._view.number;
    if (newest) {
      this._view = envelope;
      this._acknowledge(envelope.last_processed);
    }
    rejections.forEach(function (rejection) {
      self._notify("rejected", [rejection.number, rejection.reason]);
    });
    if (!newest) { return; }
    this._notify("view", [envelope.view, envelope]);
    if (envelope.ended !== null) { this._end(envelope.ended, envelope.view); }
  };

  // last_processed is the latest of the page's messages the game handled, so
  // it can belong to another socket of the page. This socket's messages reach
  // the game in the order it sent them, so one it names settles every one sent
  // before it. A null last_processed after a reconnect means the session has
  // forgotten the page's numbers, and settles what earlier connections sent.
  dlgr.Socket.prototype._acknowledge = function (last) {
    var connection = this._connection;
    var numbers = this._unacknowledged.map(function (message) { return message.number; });
    this._unacknowledged = this._unacknowledged.slice(numbers.indexOf(last) + 1);
    if (last === null) {
      this._unacknowledged = this._unacknowledged.filter(function (message) {
        return message.connection === connection;
      });
    }
  };

  dlgr.Socket.prototype._end = function (reason, view) {
    if (this._ended) { return; }
    this._ended = true;
    this._notify("ended", [reason, view]);
  };

  /**
   * Send a message to ``channel``. The ``/chat`` route publishes it to that
   * channel's subscribers, and the ``/experiment-socket`` route passes it to
   * the experiment's ``handle_websocket_message`` method, with ``channel`` as
   * the ``channel_name``.
   *
   * On a socket that joined a session, a message sent on the ``gameChannel``
   * goes to the session instead, which passes it to the game type's
   * ``apply`` method. The socket wraps it in an envelope holding the
   * message's number, and the browser's time and the session time of the
   * newest view when ``send`` is called, which the game receives as
   * ``sent``. The page numbers its messages from 1, one more each time,
   * across all of its sockets, and a reconnect never reuses a number. A
   * string payload that is JSON reaches ``apply`` parsed, and any other
   * string as it is.
   *
   * A message sent while the connection is down is held, and sent in order
   * once the connection reopens. Held messages are discarded if the socket is
   * closed or refused first, as is anything sent after that.
   *
   * @param {string} channel - Name of the channel to send to
   * @param {Object|string} payload - Message to send, encoded as JSON unless
   *   it is already a string
   * @returns {number|undefined} The message's number, for a message sent on
   *   the ``gameChannel`` of a socket that hasn't been closed or refused
   * @alias dallinger.Socket#send
   */
  dlgr.Socket.prototype.send = function (channel, payload) {
    checkSendChannel(channel);
    if (this._closed) { return; }
    var message = null;
    if (channel === this.gameChannel) {
      if (typeof payload === 'string') { payload = parsePayload(payload); }
      // The session reads an envelope only if it has a payload key, which
      // JSON.stringify leaves out for undefined.
      if (payload === undefined) { payload = null; }
      message = {number: lastMessageNumber + 1, payload: payload, connection: null};
      payload = {
        envelope: {
          number: message.number,
          browser_time: browserTime(),
          view_time: this._view === null ? null : this._view.time
        },
        payload: payload
      };
    }
    var frame = channel + ':' + (typeof payload === 'string' ? payload : JSON.stringify(payload));
    if (message !== null) {
      lastMessageNumber = message.number;
      this._unacknowledged.push(message);
    }
    if (this.raw.readyState === WebSocket.OPEN) {
      this.raw.send(frame);
      if (message !== null) { message.connection = this._connection; }
    } else {
      this._pending.push(frame);
    }
    if (message !== null) { return message.number; }
  };

  /**
   * Call ``callback`` with each message published to this socket's channel,
   * whether it was sent by the experiment or by another client.
   *
   * The callback is passed the payload parsed as JSON, or the payload string
   * itself if it is not JSON, followed by the payload string.
   *
   * @param {function} callback - Called with each message
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onBroadcast
   */
  dlgr.Socket.prototype.onBroadcast = function (callback) {
    if (this.channel === null) {
      throw new Error("This socket was opened without a channel, so it receives no broadcasts.");
    }
    this._callbacks.broadcast.push(callback);
    return this;
  };

  /**
   * Call ``callback`` with each message sent to this participant with the
   * experiment's ``publish_to_participants`` method. The callback is passed
   * the same arguments as an ``onBroadcast`` callback.
   *
   * @param {function} callback - Called with each message
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onDirect
   */
  dlgr.Socket.prototype.onDirect = function (callback) {
    if (this.participantId == null) {
      throw new Error("This socket was opened without a participant id, so it cannot be sent directed messages.");
    }
    this._callbacks.direct.push(callback);
    return this;
  };

  /**
   * Call ``callback`` each time the connection opens, including after a
   * reconnect. Messages published while the connection was down are not
   * replayed, so this is where a page should fetch anything it may have
   * missed. Messages held by ``send`` have already been sent when the
   * callback runs.
   *
   * The callback is passed the ``open`` event, whose ``isReconnect`` property
   * is ``false`` the first time the connection opens.
   *
   * @param {function} callback - Called with the ``open`` event
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onOpen
   */
  dlgr.Socket.prototype.onOpen = function (callback) {
    this._callbacks.open.push(callback);
    return this;
  };

  /**
   * Call ``callback`` with the close code and reason if the server refuses the
   * connection, as the ``/experiment-socket`` route does for an unknown
   * participant. The connection is not retried either way, and without a
   * callback the refusal is logged to the console.
   *
   * @param {function} callback - Called with the close code and reason
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onRefused
   */
  dlgr.Socket.prototype.onRefused = function (callback) {
    this._callbacks.refused.push(callback);
    return this;
  };

  dlgr.Socket.prototype._onSession = function (kind, callback) {
    if (this.session === null) {
      throw new Error("This socket was opened without a session, so it receives nothing from one.");
    }
    this._callbacks[kind].push(callback);
    return this;
  };

  /**
   * Call ``callback`` with each new view of the session, what the game
   * type's ``view`` method lets this player see. The session sends one each
   * time the connection opens, unless it has ended, and others as the game
   * goes on.
   *
   * Views can arrive out of order, so only a view newer than the last one
   * passed to the callback is passed to it, and an older view that arrives
   * late is dropped. One view is newer than another if the session sent it
   * later, which its envelope's ``number`` says.
   *
   * The callback is passed the view, followed by its envelope, an object
   * holding:
   *
   * - ``view``: the view itself
   * - ``number``: a later view has a higher number
   * - ``time``: the session time the view shows, in seconds
   * - ``kind``: ``"tick"`` for a view sent after a tick, otherwise
   *   ``"message"``
   * - ``last_processed``: the number of the latest message from this page that
   *   the game has handled, or ``null``
   * - ``rejected``: the messages the game rejected since the page's last view,
   *   also passed to ``onRejected``
   * - ``ended``: why the session ended, once it has, otherwise ``null``
   * - ``clock``: the server's clock when it started playing the session for
   *   this view, in seconds since 1970. The view leaves a little after.
   *
   * When the connection drops and reopens, the socket joins the session again
   * and the next view shows the game as it is. The session forgets a page's
   * ``last_processed`` and its unreported rejections when the page's last
   * connection closes, so that view doesn't say which messages sent before
   * the drop the game handled, only what they changed, and a rejection made
   * just before the drop is never reported.
   *
   * @param {function} callback - Called with each new view and its envelope
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onView
   */
  dlgr.Socket.prototype.onView = function (callback) {
    return this._onSession("view", callback);
  };

  /**
   * Call ``callback`` once for each message the game type's ``apply`` method
   * rejected, with the number ``send`` returned for it and the reason the
   * game gave. A rejection arrives with a view, and is reported even if that
   * view is older than one already passed to ``onView``. A message sent
   * without the socket's envelope is never reported, and neither is one
   * rejected just before the connection dropped (see ``onView``). The session
   * reports a page's rejections to each of its sockets, so a page with two
   * sockets in one session hears each rejection on both.
   *
   * @param {function} callback - Called with the message's number and the
   *   reason
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onRejected
   */
  dlgr.Socket.prototype.onRejected = function (callback) {
    return this._onSession("rejected", callback);
  };

  /**
   * Call ``callback`` once, when the page learns that its session has ended,
   * with why it ended and this player's final view. The page learns it from
   * the first view that says so, from the ending the session sends instead of
   * a view to a page that joins once it has ended, or from the saved result,
   * whichever comes first. The final view can still reach ``onView``
   * afterwards. The session's result may not be saved yet. See
   * ``resultSaved``.
   *
   * @param {function} callback - Called with the reason and the final view
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onEnded
   */
  dlgr.Socket.prototype.onEnded = function (callback) {
    return this._onSession("ended", callback);
  };

  /**
   * Call ``callback`` once, when the session's result has been saved, so the
   * page can move on. It is passed the same object ``resultSaved`` resolves
   * with.
   *
   * @param {function} callback - Called with the saved result
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onResultSaved
   */
  dlgr.Socket.prototype.onResultSaved = function (callback) {
    return this._onSession("saved", callback);
  };

  /**
   * Wait for the session's result to be saved. A page should wait for this
   * before it is submitted, so the experiment can read the result.
   *
   * The returned promise resolves with an object holding:
   *
   * - ``status``: ``"ended"``, or ``"failed"`` if the game's code failed
   * - ``reason``: why the session ended
   * - ``view``: this player's final view
   *
   * A failed session's result is saved too, so the page can move on either
   * way. ``onEnded`` says when the session has ended, for a page that
   * shouldn't wait for the save indefinitely. The promise is rejected if the
   * socket is closed first, or if the server refuses it, as it does once an
   * ended session's record has expired. A refusal passes the close code and
   * reason.
   *
   * @example
   * socket.resultSaved().done(function (result) {
   *   dallinger.goToPage('questionnaire');
   * });
   *
   * @returns {jQuery.Promise} See :ref:`deferreds-label`
   * @alias dallinger.Socket#resultSaved
   */
  dlgr.Socket.prototype.resultSaved = function () {
    if (this.session === null) {
      throw new Error("This socket was opened without a session, so it has no result.");
    }
    return this._saved.promise();
  };

  /**
   * Close the connection for good, discarding any messages held by ``send``.
   *
   * The returned ``Deferred`` resolves once the connection has closed, so
   * that a page can let messages it has already sent reach the server before
   * it navigates away.
   *
   * @example
   * socket.send('chatroom', {type: 'log', content: 'Goodbye.'});
   * socket.close().always(function () {
   *   dallinger.goToPage('questionnaire');
   * });
   *
   * @returns {jQuery.Deferred} See :ref:`deferreds-label`
   * @alias dallinger.Socket#close
   */
  dlgr.Socket.prototype.close = function () {
    var deferred = $.Deferred();
    var raw = this.raw;
    this._stop();
    // ReconnectingWebSocket's close() leaves an already scheduled reconnect in
    // place, and its timer calls open() on this instance.
    raw.open = function () {};
    if (raw.readyState === WebSocket.OPEN) {
      raw.addEventListener("close", function () { deferred.resolve(); });
    } else {
      // Between retries there is no underlying socket to fire a close event,
      // and nothing has been sent that could still be in flight.
      deferred.resolve();
    }
    raw.close();
    return deferred;
  };

  /**
   * Open a WebSocket connection to the ``/chat`` route, which publishes each
   * message it is sent to the channel the message names.
   *
   * The connection identifies the participant from ``dallinger.identity``.
   *
   * @example
   * var chatroom = dallinger.openChatSocket({channel: 'chatroom'});
   * chatroom.onBroadcast(function (data) {
   *   if (data.type === 'message') { ... }
   * });
   * chatroom.send('chatroom', {type: 'message', content: 'Hello'});
   *
   * @param {Object} [options]
   * @param {string} [options.channel] - Channel to subscribe to, whose
   *   messages are passed to ``onBroadcast`` callbacks
   * @param {string} [options.scope=dallinger.pageScope] - Scope of the
   *   connection; ``null`` sends none
   * @param {number} [options.session] - Id of the real-time session to join,
   *   which ``create_realtime_session`` returned. The participant must be
   *   one of its players. Keep the default scope: with a ``null`` one, the
   *   session's views for this page reach every page the player has open,
   *   and those pages take them for their own.
   * @param {string} [options.gameChannel] - Channel of the session's game
   *   type, needed with ``session``
   * @returns {dallinger.Socket} The new connection
   */
  dlgr.openChatSocket = function (options) {
    return new dlgr.Socket("/chat", options);
  };

  /**
   * Open a WebSocket connection to the ``/experiment-socket`` route, which
   * passes each message it is sent to the experiment's
   * ``handle_websocket_message`` method on the web process holding the
   * connection.
   *
   * The connection identifies the participant from ``dallinger.identity``,
   * and the server refuses it if that participant does not exist or the
   * experiment's ``accept_websocket_connection`` method says no.
   *
   * @example
   * var socket = dallinger.openExperimentSocket();
   * socket.onDirect(function (data) {
   *   if (data.type === 'move_accepted') { ... }
   * });
   * socket.send('moves', {type: 'move', action: 'rock'});
   *
   * @param {Object} [options] - The same options as
   *   ``dallinger.openChatSocket``
   * @returns {dallinger.Socket} The new connection
   */
  dlgr.openExperimentSocket = function (options) {
    return new dlgr.Socket("/experiment-socket", options);
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
    var deferred = $.Deferred();
    // The quorum socket is not a request idle sleep can see.
    if (window.dallingerPresence) {
      window.dallingerPresence.setWaiting(true);
      deferred.always(function () { window.dallingerPresence.setWaiting(false); });
    }
    dlgr.openChatSocket({channel: "quorum"}).onBroadcast(function (data) {
      dlgr.updateProgressBar(data.n, data.q);
      if (data.n === data.q) {
        deferred.resolve();
      }
    });
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
