Using Scientific Python Libraries
=================================

Heroku has a general purpose runtime, suitable to run many kinds of Python
applications. Dallinger experiments sometimes might require one or two
specialized dependencies that could be difficult to integrate with this
generic runtime.

An example of these specialized libraries is `Scipy <https://scipy.org>`__.
Though this can be a very useful addition to a Dallinger experiment, it's
not as simple to include as most Python libraries.

Heroku offers a couple of mechanisms to add specialized dependencies. The
recommended way is using their support for `Dockerfile` based apps. See their
`FAQ about this question <https://help.heroku.com/S48C2M3H/can-i-use-scientific-python-libraries-scipy-scikit-learn-etc-on-heroku>`__ for details,
including how to use their docker support and where to find an example
application for basing your work.

The other option is to use `buildpacks <https://devcenter.heroku.com/articles/buildpacks>`__, which are basically a set of scripts that can retrieve
dependencies, compile code, and more. Though Heroku does not officially
support them, there are various third-party buildpacks that can be used to
integrate dependencies with Dallinger.

Buildpacks for specific dependencies can be varied in their support of
Python and dependency versions, so it's not possible to just pick one as the
"best" and link to it. Instead, here are links to some important libraries
in the form of Heroku buildpack searches. Pick the one that best fits your
use case:

- `Scipy <https://elements.heroku.com/search/buildpacks?q=scipy>`__
- `Numpy <https://elements.heroku.com/search/buildpacks?q=numpy>`__
- `Scikit Learn <https://elements.heroku.com/search/buildpacks?q=sklearn>`__
