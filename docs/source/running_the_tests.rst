Running the tests
=================

If you push a commit to a branch in the Dallinger organization on GitHub,
or open a pull request from your own fork, Dallinger's automated code tests
will be run on `GitHub <https://github.com/>`_.

Current build status: |status|

.. |status| image:: https://github.com/Dallinger/Dallinger/workflows/continuous-integration/badge.svg
   :target: https://github.com/Dallinger/Dallinger/actions?query=workflow%3Acontinuous-integration

The tests include:

* Making sure that a source distribution of the Python package can be created.
* Running `flake8 <https://flake8.readthedocs.io>`_ to make sure Python code
  conforms to the `PEP 8 <https://www.python.org/dev/peps/pep-0008/>`_ style guide.
* Running the tests for the Python code using `pytest <http://doc.pytest.org/>`_
  and making sure they pass on Python 3.9, 3.10, 3.11, and 3.12.
* Making sure that `code coverage <https://coverage.readthedocs.io/>`_
  for the Python code is above the desired threshold.
* Making sure the docs build without error.

If you see ImportErrors related to demo packages, this most likely means you
have not installed the ``dlgr.demos`` sub-package. See the
:doc:`Dallinger development installation instructions
<developing_dallinger_setup_guide>` for details.

Amazon Mechanical Turk Integration Tests
----------------------------------------

You can also run all these tests locally, with some additional requirements:

* The Amazon Web Services credentials set in .dallingerconfig must correspond
  to a valid MTurk Sandbox
  `Requester <https://requester.mturk.com/mturk/beginsignin>`__ account.
* Some tests require access to an MTurk Sandbox
  `Worker <https://workersandbox.mturk.com/mturk/welcome>`__ account, so you
  should create this account (probably using the same AWS account as above).
* The Worker ID from the Worker account (visible on the
  `dashboard <https://workersandbox.mturk.com/mturk/dashboard>`__) needs to be
  set in ``tests/config.py``, which should be created by making a copy of
  ``tests/config.py.in`` before setting the value. ``tests/config.py`` is
  excluded from version control, so your Id will not be pushed to a remote
  repository.

Commands
--------

Tests
~~~~~

You can run all tests locally, simply by running::

	tox

To run just the fastest Python tests (it's recommended to run these tests first)::

	pytest

To run include slower Python tests::

	pytest --runslow

To run the Python tests excluding those that interact with Amazon Mechanical
Turk, run::

	pytest -m "not mturk"

To run all tests except those that require a MTurk Worker ID, run::

	pytest -m "not mturkworker"

To run the complete, comprehensive suite of tests which interact Mechanical Turk,
add the ``mturkfull`` option when running the tests::

  pytest --mturkfull --runslow

To run the JavaScript tests, run::

  npm run test --coverage


Linting
~~~~~~~

To run black::

  black dallinger

To run flake8::

	flake8
