Docker support
==============

Dallinger has experimental support for running experiments in docker.

Usage
~~~~~

A new CLI command has been added: `dallinger docker`.

It currently has a single subcommand, `dallinger docker debug`, with the same usage
as `dallinger debug`.

.. note::

    These commands do not require redis or postgresql already installed: they will be run
    via docker-compose by dallinger automatically.

Every experiment will use its own redis and postgresql isolated instance.

If dallinger was installed in editable mode (for instance via `pip install -e .`)
the code from the editable install will be made available to the containers to use.
The egg will not be reinstalled in this case, so any changes that require a reinstall
will also require an image rebuild.

Images can be rebuilt in the project root with:

.. code-block:: shell

    docker build . --target dallinger -t dallingerimages/dallinger
    docker build . --target dallinger-bot -t dallingerimages/dallinger-bot

How it works
~~~~~~~~~~~~

Under the hood `dallinger docker` creates a `docker-compose.yml` file inside the
temporary directory where the experiment is assembled.

This means that, while it's running all regular `docker-compose` commands can be
issued by either entering that directory or by passing docker-compose the location
of the yaml file using the `-f` option.

Examples:

.. code-block:: shell

    # to display output from web and worker containers:
    docker-compose -f ${EXPERIMENT_TMP_DIR}/docker-compose.yml logs -f web worker
    # To start a shell inside the worker container:
    docker-compose -f ${EXPERIMENT_TMP_DIR}/docker-compose.yml exec worker bash


Images
~~~~~~

Two images are provided: `dallinger` and `dallinger-bot`.
The latter is signifincantly bigger and only used when running with the `--bot` flag.
