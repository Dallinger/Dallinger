Docker tutorial
===============

If you're new to Docker, this tutorial will go through the basic concepts
you need to get started.

This tutorial assumes you already installed Docker and dallinger with the
Docker extra (using a command like ``pip install --user dallinger[docker,data]``).

Images
------

Docker images are collections of files that contain the application code and
configuration that you want to run.

Dallinger ships with a basic image that is used as a base when you build your
experiment image.

When the experiment image is built, everything needed to run the experiment will
be present inside the image.

To list the images in your system, run:

.. code-block:: shell

    $ docker images
    REPOSITORY   TAG       IMAGE ID   CREATED   SIZE

The above output shows that there are no images in your system.
Now let's build a Docker image for one of the demo experiments:

.. code-block:: shell

    $ cd demos/dlgr/demos/bartlett1932
    $ dallinger docker build
    ❯❯ Experiment UID: 3b72e1fb-9302-cc1a-ebae-f2cb8907dce0
    Deployment temp directory: /tmp/tmpt3cqkrss/3b72e1fb-9302-cc1a-ebae-f2cb8907dce0
    Image ghcr.io/dallinger/dallinger/bartlett1932:e3ca8804 not found - building
    ...
    Built image: ghcr.io/dallinger/dallinger/bartlett1932:e3ca8804

Dallinger invoked ``docker`` to build an image for the experiment. It used the dallinger
image corresponding to the version specified in the experiment's ``constraints.txt``
file as a base, added the experiment to it, and packaged it up in a new Docker image.
The new image will now show up if you list Docker images:

.. code-block:: shell

    $ docker images
    REPOSITORY                                 TAG        IMAGE ID       CREATED               SIZE
    ghcr.io/dallinger/dallinger/bartlett1932   e3ca8804   116af68a0905   About a minute ago    471MB


Now that the image has been generated we can run the experiment:

.. code-block:: shell

    $ dallinger docker debug
        ____        ____
       / __ \____ _/ / (_)___  ____ ____  _____
      / / / / __ `/ / / / __ \/ __ `/ _ \/ ___/
     / /_/ / /_/ / / / / / / / /_/ /  __/ /
    /_____/\__,_/_/_/_/_/ /_/\__, /\___/_/
                            /____/
                                     v7.8.0a1
    
                    Laboratory automation for
           the behavioral and social sciences.
    
    
    ❯❯ Experiment UID: 1358650b-64fc-dbb1-c87b-22c40159118a
    Deployment temp directory: /tmp/tmp49p0dgh3/1358650b-64fc-dbb1-c87b-22c40159118a
    ...
    ❯❯ Monitoring the Heroku Local server for recruitment or completion...

Dallinger created a ``docker-compose.yml`` file to run the experiment and started all the necessary services,
namely:

* A postgresql database
* A redis server
* An http server to serve the experiment
* A worker process


If you leave the current ``dallinger docker debug`` command running and run ``docker ps`` in a different terminal
you can see the four containers created:

.. code-block:: shell

    $ docker ps
    CONTAINER ID   IMAGE                   COMMAND                  CREATED          STATUS                    PORTS                                       NAMES
    edef75321fcc   bartlett1932:e3ca8804   "dallinger_heroku_web"   11 minutes ago   Up 11 minutes             0.0.0.0:5000->5000/tcp, :::5000->5000/tcp   bartlett1932_web_1
    7fe2d5bda159   bartlett1932:e3ca8804   "dallinger_heroku_wo…"   11 minutes ago   Up 11 minutes                                                         bartlett1932_worker_1
    0c3cd206983d   redis                   "docker-entrypoint.s…"   11 minutes ago   Up 11 minutes (healthy)   0.0.0.0:6379->6379/tcp, :::6379->6379/tcp   bartlett1932_redis_1
    12f8bb837a91   postgres:12             "docker-entrypoint.s…"   11 minutes ago   Up 11 minutes (healthy)   0.0.0.0:5432->5432/tcp, :::5432->5432/tcp   bartlett1932_postgresql_1

.. note::

    The ``heroku`` part in the ``COMMAND`` column is there just for historical reasons, even if we're not using Heroku at all in this tutorial.

The ``PORTS`` column shows the ports that the containers are exposing. In particular the experiment will be reachable
on port ``5000``.

We can see the logs for each container using the ``docker container logs`` command, followed by the container name or id:

.. code-block:: shell

    $ docker container logs bartlett1932_web_1

or we can follow the logs by adding ``-f`` to the previous command:

.. code-block:: shell

    $ docker container logs -f bartlett1932_web_1

When you stop the ``dallinger docker debug`` command by hitting Ctrl-C, the containers will be stopped, but not removed.
They will not be visible when running ``docker ps`` since they're stopped, but they will be visible when running
``docker ps -a``:

.. code-block:: shell

    $ docker ps 
    CONTAINER ID   IMAGE     COMMAND   CREATED   STATUS    PORTS     NAMES
    $ docker ps  -a
    CONTAINER ID   IMAGE                   COMMAND                  CREATED              STATUS                     PORTS     NAMES
    93a0a61495a6   bartlett1932:e3ca8804   "dallinger_heroku_wo…"   About a minute ago   Exited (0) 8 seconds ago             bartlett1932_worker_1
    d78af2bfcf31   bartlett1932:e3ca8804   "dallinger_heroku_web"   About a minute ago   Exited (0) 4 seconds ago             bartlett1932_web_1
    0c3cd206983d   redis                   "docker-entrypoint.s…"   35 minutes ago       Exited (0) 3 seconds ago             bartlett1932_redis_1
    12f8bb837a91   postgres:12             "docker-entrypoint.s…"   35 minutes ago       Exited (0) 3 seconds ago             bartlett1932_postgresql_1
