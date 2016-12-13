Running the tests
=================

If you push a commit to a branch in the Dallinger organization on GitHub,
or open a pull request from your own fork, Dallinger's automated code tests
will be run on `Travis <https://travis-ci.org/>`_.

Current build status: |status|

.. |status| image:: https://travis-ci.org/Dallinger/Dallinger.svg?branch=master
   :target: https://travis-ci.org/Dallinger/Dallinger

The tests include:

* Making sure that a source distribution of the Python package can be created.
* Running `flake8 <https://flake8.readthedocs.io>`_ to make sure Python code
  conforms to the `PEP 8 <https://www.python.org/dev/peps/pep-0008/>`_ style guide.
* Running the tests for the Python code using `nose <http://nose.readthedocs.io/>`_
  and making sure they pass in Python 2.7.
* Making sure that `code coverage <https://coverage.readthedocs.io/>`_
  for the Python code is above the desired threshold.
* Making sure the docs build without error.

You can also run all these tests locally, simply by running::

	tox

To run just the Python tests::

	nosetests

To build documentation::

	tox -e docs

To run flake8::

	flake8
