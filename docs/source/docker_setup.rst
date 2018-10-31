Dallinger with Docker
=====================

With the release of Dallinger version 5.0.0, we have created a Python script that uses `docker-compose <https://docs.docker.com/compose/>`__ to provide an automated installation and configuration of Dallinger to run experiments.

The code and detailed instructions can be found in this `github repository <https://github.com/Dallinger/Dockerfiles/blob/master/README.md/>`__.

Please note that we consider this to be a working yet experimental method of running Dallinger. It adds an extra level of complexity which can potentially get in the way when trying to create and debug a new experiment as debugging is more diffcult than when using Dallinger natively or in a virtual machine.
Having said that, there are can be certain advantages to this method, since Docker can install everything required to run Dallinger quickly in comparison to installing all the requirements yourself, and on platforms such as Microsoft Windows where a native installation is not possible.