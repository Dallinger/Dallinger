Running Experiments Programmatically
====================================

.. currentmodule:: dallinger.experiment

Dallinger experiments can be run through a high-level Python API.

::

    import dallinger

    experiment = dallinger.experiments.Bartlett1932()
    data = experiment.run(
        mode="live",
        base_payment=1.00,
    )

All parameters in ``config.txt`` and ``.dallingerconfig`` can be specified
in the configuration dictionary passed to the
:meth:`~Experiment.run` function. The return
value is an object that allows you to access all the Dallinger data tables
in a variety of useful formats. The following data tables are available::

    data.infos
    data.networks
    data.nodes
    data.notifications
    data.participants
    data.questions
    data.transformations
    data.transmissions
    data.vectors

For each of these tables, e.g. ``networks``, you can access the data in a
variety of formats, including::

    data.networks.csv    # Comma-separated value
    data.networks.dict   # Python dictionary
    data.networks.df     # pandas DataFrame
    data.networks.html   # HTML table
    data.networks.latex  # LaTeX table
    data.networks.list   # Python list
    data.networks.ods    # OpenDocument Spreadsheet
    data.networks.tsv    # Tab-separated values
    data.networks.xls    # Legacy Excel spreadsheet
    data.networks.xlsx   # Modern Excel spreadsheet
    data.networks.yaml   # YAML

See :doc:`classes` for more details about these tables.


Parameterized Experiment Runs
-----------------------------

This high-level API is particularly useful for running an experiment in a
loop with modified configuration for each run. For example, an experimenter
could run repeated ConcentrationGame experiments with varying numbers of
participants::

    import dallinger

    collected = []
    experiment = dallinger.experiments.ConcentrationGame()
    for run_num in range(1, 10):
        data = experiment.run(
            mode="live",
            num_participants=run_num,
        )
        collected.append(data)

With this technique, an experimenter can use data from prior runs to
modify the configuration for subsequent experiment runs.


Repeatability
-------------

It is often useful to share the code used to run an experiment in a way
that ensures that re-running it will retrieve the same results. Dallinger
provides a special method for that purpose: :meth:`~Experiment.collect`.
This method is similar to :meth:`~Experiment.run` but it requires an `app_id`
parameter. When that `app_id` corresponds to existing experiment data that
can be retrieved (from either a local export or stored remotely), that data
will be loaded. Otherwise, the experiment is run and the data is
saved under the provided `app_id` so that subsequent calls to
:meth:`~Experiment.collect` with that `app_id` will retrieve the data instead
of re-running the experiment.

For example, an experimenter could pre-generate a UUID using `dallinger uuid`,
then collect data using that UUID::

    import dallinger

    my_app_id = "68f73876-48f3-d1e2-4df7-25e46c99ce28"
    experiment = dallinger.experiments.Bartlett1932()
    data = experiment.collect(my_app_id,
        mode="live",
        base_payment=1.00,
    )

The first run of the above code will run a live experiment and collect data.
Subsequent runs will retrieve the data collected during the first run.


Importing Your Experiment
-------------------------

You can use this API directly on an imported experiment class if it is
available in your python path::

    from mypackage.experiment import MyFancyExperiment
    data = MyFancyExperiment().run(...)


Alternatively, an experiment installed as a python package can register itself
with Dallinger and appear in the experiments module. This is done by including
a `dallinger.experiments` item in the `entry_points` argument in the call to
`setup` in an experiment's `setup.py`. For example::

    ...
    setup(
        ...,
        entry_points={'dallinger.experiments': ['mypackage.MyFancyExperiment']},
        ...
    )


An experiment package registered in this manner can be imported from
`dallinger.experiments`::

    import dallinger

    experiment = dallinger.experiments.MyFancyExperiment()
    experiment.run(...)

See the `setup.py` from `dlgr.demos` for more examples.
