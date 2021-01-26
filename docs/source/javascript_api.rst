Javascript API
==============

Dallinger provides a javascript API to facilitate creating web-based
experiments. All of the dallinger demos use this API to communicate
with the experiment server. The API is defined in the `dallinger2.js`
script, which is included in the default experiment templates.

The `dallinger` object
----------------------

Any page that includes `dallinger2.js` script will have a `dallinger`
object added to the `window` global namespace. This object defines a
number of functions for interacting with Dallinger experiments.

Making requests to experiment routes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

`dallinger` provides functions which can be used to asynchronously
interact with any of the experiment routes described in
:doc:`Web API <web_api>`:

.. js:autofunction:: dallinger.get

.. js:autofunction:: dallinger.post


The `dallinger` object also provides functions that make requests
to specific experiment routes:

.. js:autofunction:: dallinger.createAgent

.. js:autofunction:: dallinger.createInfo

.. js:autofunction:: dallinger.getInfo

.. js:autofunction:: dallinger.getInfos

.. js:autofunction:: dallinger.getReceivedInfos

.. js:autofunction:: dallinger.getTransmissions


Additionally, there is a helper method to handle error responses
from experiment API calls (see :ref:`deferreds-label` below):

.. js:autofunction:: dallinger.error


.. _deferreds-label:

`Deferred` objects
~~~~~~~~~~~~~~~~~~

All of the above functions make use of `jQuery.Deferred <https://api.jquery.com/jquery.deferred/>`__,
and return `Deferred` objects. These `Deferred` objects provide the following
methods to facilitate handling asynchronous responses once they've completed:

    * ``.done(callback)``: Provide a callback to handle data from a successful
      response
    * ``.fail(fail_callback)``: Provide a callback to handle error responses
    * ``.then(callback[, fail_callback, progress_callback])``: Provide
      callbacks to handle successes, failures, and progress updates.

The fail_callback function will be passed a `dallinger.AjaxRejection` object which
includes detailed information about the error. Unexpected errors should be handled
by calling the :func:`dallinger.error` method with the `AjaxRejection` object.


Experiment Initialization and Completion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In addition to the request functions above, there are a few functions that are
used by the default experiment templates to setup and complete an experiment.
If you are writing a highly customized experiment, you may need to use
these explicitly:

.. js:autofunction:: dallinger.createParticipant

.. js:autofunction:: dallinger.loadParticipant

.. js:autofunction:: dallinger.hasAdBlocker

.. js:autofunction:: dallinger.submitAssignment

.. js:autofunction:: dallinger.submitQuestionnaire

.. js:autofunction:: dallinger.waitForQuorum


Helper functions and properties
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Finally, there are a few miscellaneous utility functions and properties
which are useful when writing a custom experiment:

.. js:autofunction:: dallinger.getUrlParameter

.. js:autofunction:: dallinger.goToPage

.. js:autoattribute:: dallinger.identity
