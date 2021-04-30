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
    via docker-compose by dallinger automatically.

Every experiment will use its own redis and postgresql isolated instance.

If dallinger was installed in editable mode (for instance via ``pip install -e .``)
the code from the editable install will be made available to the containers to use.
The egg will not be reinstalled in this case, so any changes that require a reinstall
will also require an image rebuild.


How it works
------------

Under the hood ``dallinger docker`` creates a ``docker-compose.yml`` file inside the
temporary directory where the experiment is assembled.

This means that, while it's running all regular ``docker-compose`` commands can be
issued by either entering that directory or by passing docker-compose the location
of the yaml file using the ``-f`` option.

Examples:

.. code-block:: shell

    # to display output from web and worker containers:
    docker-compose -f ${EXPERIMENT_TMP_DIR}/docker-compose.yml logs -f web worker
    # To start a shell inside the worker container:
    docker-compose -f ${EXPERIMENT_TMP_DIR}/docker-compose.yml exec worker bash

Image creation
**************

Make sure your experiment specifies an ``image_base_name`` for your image.
The specified ``image_base_name`` should include the docker registry you want to use and
the destination where the docker image should be pushed.
The ``bartlett1932`` experiment, for instance, has it set to ``ghcr.io/dallinger/dallinger/bartlett1932``
to push to the Github container registry.

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

Deploying an experiment
***********************

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
