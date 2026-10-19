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

  var browserTimeAt = function (performanceNow) {
    return (performance.timeOrigin + performanceNow) / 1000;
  };

  // The library reads the clock through this, not the public name, so that
  // a page replacing dallinger.browserTime can't split envelopes from
  // measurements.
  var readBrowserTime = function () {
    return browserTimeAt(performance.now());
  };

  /**
   * The time now on the browser's clock, in seconds since 1970. Use it to
   * note when something happened on the page, and pass that time to a
   * session socket's ``serverTime`` to put it on the server's clock.
   *
   * This clock keeps counting steadily even if someone changes the
   * computer's clock while the page is open. The browser time in a message
   * sent to a session (see ``dallinger.Socket#send``) comes from it too.
   *
   * A browser event's ``timeStamp`` comes from the same clock, counted in
   * milliseconds from ``performance.timeOrigin``, so an event's browser time
   * is ``(performance.timeOrigin + event.timeStamp) / 1000``. That is closer
   * to the moment a key was pressed or the mouse clicked than calling
   * ``browserTime`` in the event handler.
   *
   * @example
   * document.addEventListener('keydown', function (event) {
   *   var pressedAt = (performance.timeOrigin + event.timeStamp) / 1000;
   *   var pressedAtOnServer = socket.serverTime(pressedAt);
   * });
   *
   * @returns {number} Seconds since 1970
   */
  dlgr.browserTime = function () {
    return readBrowserTime();
  };

  // A run of clock sync sends this many time requests, one after another.
  var CLOCK_REQUESTS = 5;
  // A request with no answer by then is given up, and the next one sent.
  var CLOCK_ANSWER_TIMEOUT_MS = 2000;
  // The time from the end of one run to the start of the next.
  var CLOCK_SYNC_INTERVAL_MS = 30000;

  // Measures the server's clock against the browser's, keeping the answer
  // with the shortest round trip of each run, the one least delayed on the
  // way, and taking the server's clock to have been read halfway through it.
  // measured gets each run's measurement.
  var ClockSync = function (sendRequest, measured) {
    this._sendRequest = sendRequest;
    this._measured = measured;
    this.measurement = null;
    this._run = null;
    this._timer = null;
    this._lastId = 0;
  };

  ClockSync.prototype.start = function () {
    this.stop();
    this._run = {answers: [], left: CLOCK_REQUESTS, request: null};
    this._request();
  };

  ClockSync.prototype.stop = function () {
    clearTimeout(this._timer);
    this._timer = null;
    this._run = null;
  };

  ClockSync.prototype._request = function () {
    var self = this;
    var run = this._run;
    if (run.left === 0) { return this._finish(); }
    run.left -= 1;
    this._lastId += 1;
    run.request = {id: this._lastId, sentAt: performance.now()};
    this._sendRequest({type: "request", id: this._lastId});
    this._timer = setTimeout(function () { self._request(); }, CLOCK_ANSWER_TIMEOUT_MS);
  };

  ClockSync.prototype.receive = function (answer) {
    var receivedAt = performance.now();
    var request = this._run === null ? null : this._run.request;
    if (request === null || answer.id !== request.id) { return; }
    clearTimeout(this._timer);
    this._run.answers.push({
      browser_time: browserTimeAt((request.sentAt + receivedAt) / 2),
      server_time: answer.clock,
      round_trip: (receivedAt - request.sentAt) / 1000
    });
    this._request();
  };

  ClockSync.prototype._finish = function () {
    var self = this;
    var answers = this._run.answers;
    this._run = null;
    this._timer = setTimeout(function () { self.start(); }, CLOCK_SYNC_INTERVAL_MS);
    if (!answers.length) { return; }
    this.measurement = answers.reduce(function (best, answer) {
      return answer.round_trip < best.round_trip ? answer : best;
    });
    this._measured(this.measurement);
  };

  ClockSync.prototype.serverTime = function (browserTime) {
    var measurement = this.measurement;
    if (measurement === null) { return null; }
    return browserTime + measurement.server_time - measurement.browser_time;
  };

  // What a socket that joined a session knows about it.
  var SessionState = function (socket) {
    // Messages sent on the game channel that no view has acknowledged, each
    // with the connection it went out on, or null while it is held.
    this.unacknowledged = [];
    this.view = null;
    this.reportedRejections = {};
    this.ended = false;
    this.saved = $.Deferred();
    var sendTimeFrame = function (frame) {
      socket._sendFrame(dlgr.TIME_CHANNEL + ':' + JSON.stringify(frame));
    };
    this.clock = new ClockSync(sendTimeFrame, function (measurement) {
      sendTimeFrame($.extend({type: "clock"}, measurement));
      socket._notify("clock", [measurement]);
    });
  };

  /**
   * A connection to one of the experiment server's WebSocket routes, created
   * with ``dallinger.openChatSocket`` or ``dallinger.openExperimentSocket``.
   *
   * The connection is a ``ReconnectingWebSocket``, available as the ``raw``
   * property, which reconnects with a growing delay whenever it is dropped.
   * A connection the server refuses is not retried.
   *
   * A socket opened with a ``session`` is a player's page in a real-time
   * game. Each time it connects, it joins the session and is sent the game
   * as it stands, so a player whose connection drops carries on from where
   * the game has got to. Send the player's moves with ``send``, draw the
   * game in ``onView``, and move on once ``resultSaved`` says the game is
   * over and saved. The socket also keeps track of the server's clock, so
   * the page can tell the time as the game sees it (see ``sessionTime``).
   *
   * @example
   * // sessionId is the id create_realtime_session returned, which the
   * // page gets from the experiment
   * var socket = dallinger.openExperimentSocket({
   *   session: sessionId,
   *   gameChannel: 'sealed_bid'
   * });
   * socket.onView(function (view) {
   *   $('#bids-made').text(view.bids_made);
   * });
   * $('#bid').on('click', function () {
   *   socket.send('sealed_bid', {bid: Number($('#amount').val())});
   * });
   * socket.resultSaved().done(function () {
   *   dallinger.goToPage('questionnaire');
   * });
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
      view: [], rejected: [], ended: [], saved: [], clock: []
    };
    this._connection = 0;
    this._state = this.session === null ? null : new SessionState(this);
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
      var state = self._state;
      if (state !== null) {
        state.unacknowledged.forEach(function (message) {
          if (message.connection === null) { message.connection = self._connection; }
        });
        if (!state.ended) { state.clock.start(); }
      }
      self._notify("open", [event]);
    });
    this.raw.addEventListener("message", function (event) {
      self._receive(event.data);
    });
    // A drop abandons the run, and the next open starts another.
    this.raw.addEventListener("close", function () {
      if (self._state !== null) { self._state.clock.stop(); }
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
    var state = this._state;
    if (state === null) { return; }
    state.unacknowledged = state.unacknowledged.filter(function (message) {
      return message.connection !== null;
    });
    state.clock.stop();
    state.saved.reject(code, reason);
  };

  // Sends a frame now, or holds it until the connection opens, and returns
  // whether it went now.
  dlgr.Socket.prototype._sendFrame = function (frame) {
    if (this.raw.readyState === WebSocket.OPEN) {
      this.raw.send(frame);
      return true;
    }
    this._pending.push(frame);
    return false;
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
    } else if (frame.indexOf(dlgr.TIME_CHANNEL + ':') === 0) {
      if (this._state !== null) {
        this._state.clock.receive(parsePayload(frame.substring(dlgr.TIME_CHANNEL.length + 1)));
      }
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
    if (data.type === "realtime_saved" && this._state.saved.state() === "pending") {
      this._notify("saved", [data]);
      this._state.saved.resolve(data);
    }
  };

  dlgr.Socket.prototype._receiveView = function (envelope) {
    var self = this;
    var state = this._state;
    // A view that arrives late still reports its rejections.
    var rejections = envelope.rejected.filter(function (rejection) {
      if (state.reportedRejections[rejection.number]) { return false; }
      state.reportedRejections[rejection.number] = true;
      return true;
    });
    var newest = state.view === null || envelope.number > state.view.number;
    var ending = false;
    if (newest) {
      state.view = envelope;
      this._acknowledge(envelope.last_processed);
      ending = envelope.ended !== null && this._markEnded();
    }
    rejections.forEach(function (rejection) {
      self._notify("rejected", [rejection.number, rejection.reason]);
    });
    if (!newest) { return; }
    this._notify("view", [envelope.view, envelope]);
    if (ending) { this._notify("ended", [envelope.ended, envelope.view]); }
  };

  // last_processed is the latest of the page's messages the game handled, so
  // it can belong to another socket of the page. This socket's messages reach
  // the game in the order it sent them, so one it names settles every one sent
  // before it. A null last_processed after a reconnect means the session has
  // forgotten the page's numbers, and settles what earlier connections sent.
  dlgr.Socket.prototype._acknowledge = function (last) {
    var connection = this._connection;
    var state = this._state;
    var numbers = state.unacknowledged.map(function (message) { return message.number; });
    state.unacknowledged = state.unacknowledged.slice(numbers.indexOf(last) + 1);
    if (last === null) {
      state.unacknowledged = state.unacknowledged.filter(function (message) {
        return message.connection === connection;
      });
    }
  };

  dlgr.Socket.prototype._end = function (reason, view) {
    if (this._markEnded()) { this._notify("ended", [reason, view]); }
  };

  // Returns false if the socket already knew the session had ended.
  dlgr.Socket.prototype._markEnded = function () {
    if (this._state.ended) { return false; }
    this._state.ended = true;
    this._state.clock.stop();
    return true;
  };

  /**
   * Send a message to ``channel``. The ``/chat`` route publishes it to that
   * channel's subscribers, and the ``/experiment-socket`` route passes it to
   * the experiment's ``handle_websocket_message`` method, with ``channel`` as
   * the ``channel_name``.
   *
   * On a socket that joined a session, a message sent on the ``gameChannel``
   * goes only to the game, whose ``apply`` method gets it. ``send`` returns
   * the message's number, which ``onRejected`` uses to say which message
   * the game refused. A page numbers its messages 1, 2, 3 and so on, across
   * all of its sockets, and never repeats a number, even after a reconnect.
   * ``apply`` also gets ``sent``, which holds the message's number, the
   * browser time it was sent at (see ``dallinger.browserTime``), and the
   * session time of the newest view the page had then. A string that holds
   * JSON reaches ``apply`` parsed, and any other string as it is. Messages
   * over the game type's ``max_messages_per_second`` limit are dropped.
   *
   * A message sent while the connection is down waits, and goes out in
   * order once the connection reopens. Once the socket is closed or
   * refused, waiting messages are dropped and ``send`` sends nothing.
   *
   * @param {string} channel - The channel to send on
   * @param {Object|string} payload - The message. Anything but a string is
   *   sent as JSON.
   * @returns {number|undefined} The message's number, for a message sent on
   *   a session's ``gameChannel``. Nothing for any other message, or once
   *   the socket is closed or refused.
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
          browser_time: readBrowserTime(),
          view_time: this._state.view === null ? null : this._state.view.time
        },
        payload: payload
      };
    }
    var frame = channel + ':' + (typeof payload === 'string' ? payload : JSON.stringify(payload));
    if (message !== null) {
      lastMessageNumber = message.number;
      this._state.unacknowledged.push(message);
    }
    if (this._sendFrame(frame) && message !== null) {
      message.connection = this._connection;
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
   * Call ``callback`` with each new view of the game: what the game type's
   * ``view`` method lets this player see. Draw the game from it. The page
   * gets a view each time it joins the session, including after a
   * reconnect, and a new one whenever the game changes, until the session
   * ends.
   *
   * Views can arrive out of order. The callback only ever gets a view newer
   * than the last one it got, and one that arrives late is skipped, so the
   * page can always draw the view it is given.
   *
   * The callback is passed the view, then an object with details about it:
   *
   * - ``view``: the view itself
   * - ``number``: a later view has a higher number
   * - ``time``: the session time the view shows, in seconds (see
   *   ``sessionTime``)
   * - ``kind``: ``"tick"`` if the game type's ``tick`` method made the
   *   change, otherwise ``"message"``
   * - ``last_processed``: the number of this page's latest message that the
   *   game has applied or rejected (see ``send``), or ``null``
   * - ``rejected``: this page's messages the game rejected since its last
   *   view, also passed to ``onRejected``
   * - ``ended``: why the session ended, once it has, otherwise ``null``
   * - ``clock``: the server's clock, in seconds since 1970, when the
   *   session time was ``time``
   *
   * When the page's last connection to the session drops, the session
   * forgets which of the page's messages it has handled. The next view still
   * shows what those messages changed, but its ``last_processed`` is
   * ``null`` until the game handles another message, and a message rejected
   * just before the drop is never reported.
   *
   * @param {function} callback - Called with each new view and its details
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onView
   */
  dlgr.Socket.prototype.onView = function (callback) {
    return this._onSession("view", callback);
  };

  /**
   * Call ``callback`` each time the game rejects one of this page's
   * messages, with the number ``send`` returned for the message and the
   * reason the game type's ``apply`` method gave ``Reject``. Use it to tell
   * the player why a move didn't count.
   *
   * Each rejection is reported once, even if it arrives with a view too old
   * to reach ``onView``. A message rejected just before the connection
   * dropped is never reported (see ``onView``), and neither is one sent
   * other than with ``send``. A page with two sockets in the same session
   * hears each rejection on both.
   *
   * @example
   * socket.onRejected(function (number, reason) {
   *   $('#error').text('That bid didn\'t count: ' + reason);
   * });
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
   * Call ``callback`` once, as soon as the page learns the session has
   * ended, with the reason it ended and this player's final view. Use it to
   * stop taking moves and show how the game turned out. Don't submit the
   * page yet, since the result may not be saved (see ``resultSaved``).
   *
   * The reason is the one the game type's ``outcome`` method was passed:
   *
   * - ``"finished"``: the game type's ``is_over`` method returned true
   * - ``"max_duration"``: the session ran for the game type's
   *   ``max_duration``
   * - ``"not_joined"``: no player other than a bot joined within the game
   *   type's ``join_timeout``
   * - ``"failed"``: the game's code failed
   * - or the reason the experiment passed to ``end_realtime_session``
   *
   * The callback runs for a page that joins after the session has ended
   * too, though that page gets no views. For other pages, the final view
   * can reach ``onView`` after the callback has run.
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
   * page can move on. It does what ``resultSaved`` does, as a callback, and
   * is passed the same object.
   *
   * @param {function} callback - Called with the saved result
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onResultSaved
   */
  dlgr.Socket.prototype.onResultSaved = function (callback) {
    return this._onSession("saved", callback);
  };

  /**
   * Wait for the session's result to be saved. Wait for this before the
   * page is submitted or moves on, so that the experiment can read the
   * result, for example to pay a bonus.
   *
   * The returned promise resolves with an object holding:
   *
   * - ``status``: ``"ended"``, or ``"failed"`` if the game's code failed
   * - ``reason``: why the session ended (see ``onEnded``)
   * - ``view``: this player's final view
   *
   * A failed session's result is saved too, so the page can move on either
   * way. The result is usually saved a moment after the session ends. A page
   * that shouldn't wait indefinitely can use ``onEnded`` to learn that the
   * game is over before then.
   *
   * The promise is rejected if the socket is closed first, or if the server
   * refuses the connection, for example to a page that joins long after the
   * session ended. A refusal passes the close code and reason.
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
    return this._state.saved.promise();
  };

  /**
   * Call ``callback`` each time the socket measures the server's clock.
   * Most pages don't need this, since ``serverTime`` and ``sessionTime``
   * already use the measurements. It is for a page that wants to show or
   * log how closely its clock matches the server's.
   *
   * The socket measures the server's clock as soon as it connects, then
   * about every 30 seconds until the session ends. If the connection drops
   * partway through a measurement, or the server doesn't answer, that
   * measurement is skipped.
   *
   * Each measurement is also saved with the session's records, so an
   * analysis can put the browser times of players' messages on the server's
   * clock. Each one counts as a message toward the game type's
   * ``max_messages_per_second`` limit.
   *
   * The callback is passed an object holding:
   *
   * - ``browser_time``: a moment on the browser's clock (see
   *   ``dallinger.browserTime``), in seconds since 1970
   * - ``server_time``: the server's clock at that same moment, in seconds
   *   since 1970
   * - ``round_trip``: how long the server took to answer, in seconds.
   *   ``server_time`` can be off by up to half of this.
   *
   * @param {function} callback - Called with each measurement
   * @returns {dallinger.Socket} This socket
   * @alias dallinger.Socket#onClock
   */
  dlgr.Socket.prototype.onClock = function (callback) {
    return this._onSession("clock", callback);
  };

  /**
   * Convert a time on the browser's clock to the server's clock. The two
   * clocks can be seconds apart or more, so convert times before comparing
   * what happened on different players' pages. The socket lines the clocks
   * up using its latest measurement of the server's clock (see
   * ``onClock``).
   *
   * @example
   * var serverNow = socket.serverTime();
   * var clickedOnServer = socket.serverTime(clickedAt);
   *
   * @param {number} [browserTime] - A time from ``dallinger.browserTime``,
   *   in seconds since 1970. Leave it out to convert the time now.
   * @returns {number|null} The same moment on the server's clock, in seconds
   *   since 1970, or ``null`` until the socket's first measurement, which
   *   arrives shortly after it connects
   * @alias dallinger.Socket#serverTime
   */
  dlgr.Socket.prototype.serverTime = function (browserTime) {
    if (this.session === null) {
      throw new Error("This socket was opened without a session, so it has no server clock.");
    }
    return this._state.clock.serverTime(browserTime === undefined ? readBrowserTime() : browserTime);
  };

  /**
   * The session's time now, in seconds: the ``now`` the game type's methods
   * would be passed at this moment. Use it to count down to a deadline the
   * game puts in its view, or to show how long ago something in the view
   * happened.
   *
   * The socket works it out from the newest view's ``time`` and its
   * measurement of the server's clock, so it keeps counting between views.
   * The session's clock stops while the session is paused, for example
   * during a redeploy, and the page only finds out from the next view, so
   * that view can move the time back a little. Once the session has ended,
   * the time stays at the final view's time.
   *
   * @example
   * var deadline = null;
   * socket.onView(function (view) { deadline = view.deadline; });
   * setInterval(function () {
   *   var now = socket.sessionTime();
   *   if (now !== null && deadline !== null) {
   *     $('#timer').text(Math.ceil(Math.max(0, deadline - now)));
   *   }
   * }, 250);
   *
   * @returns {number|null} The session time in seconds, or ``null`` until
   *   the first view and the first measurement of the server's clock have
   *   arrived. After the session has ended, only a view is needed.
   * @alias dallinger.Socket#sessionTime
   */
  dlgr.Socket.prototype.sessionTime = function () {
    var now = this.serverTime();
    var view = this._state.view;
    if (view !== null && this._state.ended) { return view.time; }
    if (view === null || now === null) { return null; }
    return view.time + Math.max(0, now - view.clock);
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
   * @param {number} [options.session] - To play a real-time game, the id of
   *   the session, which ``create_realtime_session`` returned. The
   *   participant must be one of its players, or the server refuses the
   *   connection. Leave ``scope`` at its default: with a ``null`` scope, the
   *   game's views for this page reach every page the player has open, and
   *   each of them treats the views as its own.
   * @param {string} [options.gameChannel] - Required with ``session``: the
   *   game type's ``channel``, on which ``send`` sends the player's messages
   *   to the game
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
