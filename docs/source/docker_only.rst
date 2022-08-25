It is possible to develop with dallinger using only docker as a prerequisite.
This guide goes through the necessary steps to achieve this.

Set up services
===============

Start services needed by dallinger:

.. code-block:: shell

    docker run -d --name dallinger_redis --network=dallinger -v dallinger_redis:/data redis redis-server --appendonly yes
    docker run -d --name dallinger_postgres --network=dallinger -e POSTGRES_USER=dallinger -e POSTGRES_PASSWORD=dallinger -e POSTGRES_DB=dallinger -v dallinger_postgres:/var/lib/postgresql/data postgres:12

Start adminer:

.. code-block:: shell

    docker run -d --name dallinger_adminer --network dallinger --link dallinger_postgres:db adminer

Find the adminer ip:

.. code-block:: shell

    docker inspect -f '{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}' dallinger_adminer

Connect to adminer by visiting http://<result-of-docker-inspect>:8080
Select PostgreSQL from the dropdown, and enter `dallinger` as both username and password.


Run experiment from docker image
================================

Identify the experment image you want to use. We'll use ghcr.io/dallinger/dallinger/bartlett1932:75a9580c in this example:

.. code-block:: shell

   EXPERIMENT_IMAGE=ghcr.io/dallinger/dallinger/bartlett1932:75a9580c

Copy the contents of the experiment to a local directory to be able to work on them while running a container:

.. code-block:: shell

    docker run --rm -ti -u $(id -u ${USER}):$(id -g ${USER}) -v ${PWD}:/dest ${EXPERIMENT_IMAGE} cp -ar /experiment /dest/experiment-code

This will create a directory `experiment-code` in the current directory, containing all experiment related files.


Start the development server with docker:

.. code-block:: shell

    docker run --name dallinger --rm -ti -u $(id -u ${USER}):$(id -g ${USER}) -v ${PWD}:/dest -v ${PWD}/experiment-code:/experiment --network dallinger -p 5000:5000 -e FlASK_OPTIONS='-h 0.0.0.0' -e REDIS_URL=redis://dallinger_redis:6379 -e DATABASE_URL=postgresql://dallinger:dallinger@dallinger_postgres/dallinger ${EXPERIMENT_IMAGE} dallinger develop debug

You can now access the running dallinger instance on http://localhost:5000/dashboard
The admin password can be found in the develop `config.txt` file:

.. code-block:: shell

    grep dashboard_password experiment-code/develop/config.txt
