First step: let Dallinger user take advantage of Docker
=======================================================

Dallinger python egg split
--------------------------

The egg can be split in two: one prepares the bundle to pass to {Heroku,Docker}.

The other one runs the web server and worker in the target environment.

This way the command line can be run natively by the user.
Since it has only a few dependencies, it will be easy to package as a single "precompiled" binary.

The one that does the heavy lifting will run inside a standardized environment that will take care of the dependencies.

Supporting Dallinger users
--------------------------

A Dallinger user will need to:

  * download and install docker for their platform (Linux, Mac or Windows)
  * install the dallinger cli (the smaller egg mentioned above) from pypi or from a github releases page (we might build binaries for the three main platforms)

and will be able to:

  * Run and debug an experiment locally using docker (no Heroku dependency)
  * Build a docker image and a `docker-compose.yml` file that can be used to deploy the experiment for production use


Second step: let Dallinger developers use docker instead of Heroku
------------------------------------------------------------------

Dallinger should have support to use the currently installed version instead of the one published to pypi
