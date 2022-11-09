Docker-only installation
========================

It is possible to develop with dallinger using only docker as a prerequisite.
This means you do not need to follow most of the steps detailed in the Installation instructions.
Instead, you just need to install Docker, and create a ``.dallingerconfig`` file containing
the information requested in the Installation instructions.
Once these steps are complete, you can move forward following these instructions:

Set up services
---------------

Create the dallinger docker network (if not present already):

.. code-block:: shell

    docker network create dallinger

Start services needed by dallinger:

.. code-block:: shell

    docker run -d --name dallinger_redis --network=dallinger -v dallinger_redis:/data redis redis-server --appendonly yes
    docker run -d --name dallinger_postgres --network=dallinger -e POSTGRES_USER=dallinger -e POSTGRES_PASSWORD=dallinger -e POSTGRES_DB=dallinger -v dallinger_postgres:/var/lib/postgresql/data postgres:12

If you have these already created you can remove the existing ones and recreate them. To remove the existing ones run:

.. code-block:: shell

    # Needed if you want to recreate containers
    docker rm dallinger_redis
    docker rm dallinger_postgres

or you can start the containers you have:

.. code-block:: shell

    # Needed if you want to start stopped containers
    docker start dallinger_redis dallinger_postgres

Start adminer:

.. code-block:: shell

    docker run -d -p 8080:8080 --name dallinger_adminer --network dallinger --link dallinger_postgres:db adminer

Connect to adminer by visiting http://localhost:8080
Select PostgreSQL from the dropdown, and enter `dallinger` as both username and password. You can leave the "database" field blank to get a list of existing databases.


Run experiment from docker image
--------------------------------

Enter the experiment directory:

.. code-block:: shell

   cd /path/to/experiment-directory

Create a file named `Dockerfile` with these contents (replace image name in the `FROM` directive to match the dallinger version you depend on in your `constraints.txt` file):

.. code-block::

    # syntax = docker/dockerfile:1.2
    FROM ghcr.io/dallinger/dallinger

    RUN mkdir /experiment
    COPY requirements.txt /experiment/requirements.txt
    COPY constraints.txt /experiment/constraints.txt

    WORKDIR /experiment

    # Some experiments might only list dallinger as dependency
    # If they do the grep command will exit non-0, the pip command will not run
    # but the whole `RUN` group will succeed thanks to the last `true` invocation.
    # We remove dallinger from the dependencies since it's already present in the base image
    # and pip-installing it again might result in wasted time and space while pip
    # looks for all its dependencies and potentially reinstalls already present packages.
    RUN (grep -v ^dallinger requirements.txt > /tmp/requirements_no_dallinger.txt && \
        python3 -m pip install -r /tmp/requirements_no_dallinger.txt -c constraints.txt && \
        rm -rf /root/.cache) || true

    COPY . /experiment
    ENV PORT=5000

    CMD dallinger_heroku_web

Build a docker image for the experiment using Buildkit:

.. code-block:: shell

    EXPERIMENT_IMAGE=my-experiment
    DOCKER_BUILDKIT=1 docker build . -t ${EXPERIMENT_IMAGE}

Create an alias to start the development server with docker and run it:

.. code-block:: shell

    alias dallinger-dev-server='docker run --name dallinger --rm -ti -u $(id -u ${USER}):$(id -g ${USER}) -v ${PWD}:/experiment --network dallinger -p 5000:5000 -e FLASK_OPTIONS='-h 0.0.0.0' -e REDIS_URL=redis://dallinger_redis:6379 -e DATABASE_URL=postgresql://dallinger:dallinger@dallinger_postgres/dallinger ${EXPERIMENT_IMAGE} dallinger develop debug'
    dallinger-dev-server

You can now access the running dallinger instance on http://localhost:5000/dashboard
The admin password can be found in the develop `config.txt` file:

.. code-block:: shell

    grep dashboard_password ./develop/config.txt


Deploy the experiment image using ssh
-------------------------------------

We're going to use variations of the same command, so we create an alias for convenience.

.. code-block:: shell

    # On Linux you can use:
    alias docker-dallinger='docker run --rm -ti -v /etc/group:/etc/group -v ~/.docker:/root/.docker -v ~/.local/share/dallinger/:/root/.local/share/dallinger/ -e HOME=/root -e DALLINGER_NO_EGG_BUILD=1 -v /var/run/docker.sock:/var/run/docker.sock -v $(readlink -f $SSH_AUTH_SOCK):/ssh-agent -e SSH_AUTH_SOCK=/ssh-agent -v ${PWD}:/experiment  ${EXPERIMENT_IMAGE} dallinger'

    # On Mac Os you can use:
    alias docker-dallinger='docker run --rm -ti -v /etc/group:/etc/group -v ~/.docker:/root/.docker -v ~/.local/share/dallinger/:/root/.local/share/dallinger/ -e HOME=/root -e DALLINGER_NO_EGG_BUILD=1 -v /var/run/docker.sock:/var/run/docker.sock -v  ~/.ssh:/root/.ssh -v ${PWD}:/experiment  ${EXPERIMENT_IMAGE} dallinger'


Then we can use the alias to run dallinger inside a container:

.. code-block:: shell

    docker-dallinger docker-ssh servers list

Create a remote server with

.. code-block:: shell

    docker-dallinger docker-ssh servers add --host <your-server-name-or-ip>

And deploy to it with

.. code-block:: shell

    docker-dallinger docker-ssh deploy
