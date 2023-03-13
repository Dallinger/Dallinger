Docker support
==============

Dallinger experiments can be deployed as docker images.

This offers the advantage of increased repeatability: the code to be deployed can be prepared once,
and packed into a Docker image. The image can then be used to run the same experiment multiple times.
Since the image contains everything the experiment needs to run there will be no differences in code
acress different tuns of the experiment.

With regular Heroku builds this can't be guaranteed, since the code needs to be rebuilt on each deployment.

An account on a docker registry is necessary to publish an experiment image.
It's not necessary to deploy an existing image from a public registry.



Local development
*****************

The command ``dallinger docker debug`` allows to test an experiment locally using docker,
similarly to ``dallinger debug``.

.. note::

    The ``dallinger debug`` command does not require redis or postgresql already installed: they will be run
    via ``docker compose`` by dallinger automatically.

Every experiment will use its own redis and postgresql isolated instance.

If dallinger was installed in editable mode (for instance via ``pip install -e .``)
the code from the editable install will be made available to the containers to use.
The egg will not be reinstalled in this case, so any changes that require a reinstall
will also require an image rebuild.


How it works
------------

Under the hood ``dallinger docker`` creates a ``docker-compose.yml`` file inside the
temporary directory where the experiment is assembled.

This means that, while it's running all regular ``docker compose`` commands can be
issued by either entering that directory or by passing ``docker compose`` the location
of the yaml file using the ``-f`` option.

Examples:

.. code-block:: shell

    # to display output from web and worker containers:
    docker compose -f ${EXPERIMENT_TMP_DIR}/docker-compose.yml logs -f web worker
    # To start a shell inside the worker container:
    docker compose -f ${EXPERIMENT_TMP_DIR}/docker-compose.yml exec worker bash

Image creation
**************

Make sure your experiment specifies an ``docker_image_base_name`` for your image in its ``config.txt``.
The specified ``docker_image_base_name`` should include the docker registry you want to use and
the destination where the docker image should be pushed.
The ``bartlett1932`` experiment, for instance, has it set to ``ghcr.io/dallinger/dallinger/bartlett1932``
to push to the Github container registry.

After a succesful deployment dallinger will add the ``docker_image_name`` parameter to the experiment
``config.txt`` file. It will be used in subsequent experiment deployments to guarantee repeatability.

In the experiment directory, run

.. code-block:: shell

    dallinger docker build

Dallinger first calculates a hash based on the contents of your experiment's ``constraints.txt`` file
and the ``prepare_docker_image.sh`` script, if present.

It then builds an image for the current experiment, and tags it with the hash mentioned above.

The experiment in ``demos/dlgr/demos/bartlett1932`` for instance produces this image name:

.. code-block:: shell

    ghcr.io/dallinger/dallinger/bartlett1932:d64dbb7c

Pushing an image
****************

To push the image to the docker registry specified in your ``config.txt`` run

.. code-block:: shell

    dallinger docker push --use-existing

.. note::

    The ``--use-existing`` flag tells dallinger to use a previously generated image, if present.
    It can be safely used only when no code changed since last time the image was generated.

The push can take a long time, depending on your Internet connection speed (bartlett1932 takes
about two minutes on a 10Mb/s upload speed), more so if there are many dependencies in the experiment's
``requirements.txt`` file.

When the push is complete Dallinger will print the repository hash for the image:

.. code-block:: text

    d64dbb7c: digest: sha256:286e99f77274b8496bb9f590d3441ffa8cb3bde1681bea2499d2db029906809f size: 3044
    Pushed image: sha256:286e99f77274b8496bb9f590d3441ffa8cb3bde1681bea2499d2db029906809f

    Image ghcr.io/dallinger/dallinger/bartlett1932@sha256:286e99f77274b8496bb9f590d3441ffa8cb3bde1681bea2499d2db029906809f built and pushed.

The last line includes an image name with a sha256 based on the image contents: referencing the image that
way guarantees that it will always resolve to the same image, byte for byte.

Deploying an experiment on Heroku
*********************************

Given a docker image from a public repository Dallinger can deploy the same code in a repeatable fashion.
To deploy the image generated in the previous step using MTurk in sandbox mode run:

.. code-block:: shell

    dallinger docker deploy-image --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:eaf27845dde7dc74e361dde1a9e90f61e82fa78de57228927672058244a534a3

.. note::

    The ``dallinger docker deploy`` command is similar, but requires the user to be in an experiment directoy.

    When using ``dallinger docker deploy-image`` an experiment directory is not necessary; only an image name.

To deploy with MTurk in live mode run

.. code-block:: shell

    dallinger docker deploy-image --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:eaf27845dde7dc74e361dde1a9e90f61e82fa78de57228927672058244a534a3 --live

To override experiment parameters you can use the ``-c`` option:

.. code-block:: shell

    dallinger docker deploy-image --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:eaf27845dde7dc74e361dde1a9e90f61e82fa78de57228927672058244a534a3 -c recruiter hotair

The above will use the ``hotair`` recruiter instead of the MTurk one.


Deploying an experiment on a server
***********************************

Dallinger can use ssh and docker to deploy to a server you control. The commands to manage
experiments deployed this way can be found under the `dallinger docker-ssh` command:

.. code-block:: shell

    Usage: dallinger docker-ssh [OPTIONS] COMMAND [ARGS]...

      Deploy to a remote server using docker through ssh.

    Options:
      -h, --help  Show this message and exit.

    Commands:
      apps     List dallinger apps running on the remote server.
      deploy   Deploy a dallinger experiment docker image to a server using ssh.
      destroy  Tear down an experiment run on a server you control via ssh.
      export   Export database to a local file.
      servers  Manage remote servers where experiments can be deployed
      stats    Get resource usage stats from remote server.

.. note::

      The intended use case is a server that you provisioned exclusively for use with Dallnger.

First you need to tell dallinger a server you can use. There are some prerequisites:

    * Ports 80 and 443 should be free (Dallinger will install a web server and take care of getting SSL certificates for you)
    * ssh should be configured to enable passwordless login
    * The user on the server needs passwordless sudo

Given an IP address or a DNS name of te server and a username, add the host to the list of known dallinger servers:

.. code-block:: shell

    dallinger docker-ssh servers add --user $SERVER_USER --host $SERVER_HOSTNAME_OR_IP

Dallinger verifies that ``docker`` and ``docker compose`` are installed, and installs them if they are not.
The installation should take a couple of minutes.

Now you can deploy an experiment image to the server:

.. code-block:: shell

    dallinger docker-ssh deploy --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:0586d93bf49fd555031ffe7c40d1ace798ee3a2773e32d467593ce3de40f35b5 -c recruiter hotair -c dashboard_password foobar

In this example we use the ``hotair`` recriuter and set the dashboard password to ``foobar``.
The above command will output:

.. code-block:: shell

    Connecting to 0.0.0.0
    Connected.
    Launched http and postgresql servers. Starting experiment
    Creating database dlgr-d5543ddd
    Experiment dlgr-d5543ddd started. Initializing database
    Database initialized
    Launching experiment
    Initial recruitment list:
    https://dlgr-d5543ddd.0.0.0.0.nip.io/ad?recruiter=hotair&assignmentId=F2Q19C&hitId=BE9BWB&workerId=YC30TJ&mode=debug
    Additional details:
    Recruitment requests will open browser windows automatically.
    To display the logs for this experiment you can run:
    ssh debian@0.0.0.0 docker compose -f '~/dallinger/dlgr-d5543ddd/docker-compose.yml' logs -f
    You can now log in to the console at https://dlgr-d5543ddd.0.0.0.0.nip.io/dashboard as user admin using password foobar

Dallinger uses the free service [nip.io](https://nip.io/) to provide a URL for the experiment to get an SSL certificate from Let's Encrypt.
The experiment URL is a combination of the app id and the server IP. In this case the id of the deployed experiment is ``dlgr-d5543ddd``.

If you need to run an experiment on Amazon Mechanical Turk in sandbox mode you can set the mode to ``sandbox`` using the `-c` option like this:

.. code-block:: shell

    dallinger docker-ssh deploy --image ghcr.io/dallinger/dallinger/bartlett1932@sha256:0586d93bf49fd555031ffe7c40d1ace798ee3a2773e32d467593ce3de40f35b5 -c mode sandbox


To export the data from an experiment running on a server, run:

.. code-block:: shell

    dallinger docker-ssh export --app $APP_ID

To stop an experiment and remove its containers from the server, run:

.. code-block:: shell

    dallinger docker-ssh destroy --app $APP_ID

.. note::

      When deploying to a server using docker, the experiment can save files to the directory ``/var/lib/dallinger``.
      This directory will be visible on the server as ``~/dallinger-data/${experiment_id}``.


Support for python dependencies in private repositories
*******************************************************

An experiment can depend on a package that is in a private repository.
Dallinger will use the ssh agent to authenticate against the remote repository.
In this case the dependency needs to be specified with the `git+ssh` protocol:

.. code-block::

    git+ssh://git@github.com/<orgname>/<reponame>#egg=<eggname>

Dallinger will make docker checkout the private repository using the ssh agent.
The package will be included in the experiment image, but the credentials used
to download it will not.


.. note::

    The ssh agent needs to be running, the ``SSH_AUTH_SOCK`` environment variable should point
    to its socket path and the ssh key needed for the server needs to be loaded.
    You chan check the latter with `ssh-add -l`.
