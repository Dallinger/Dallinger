Python module
=============

Dallinger experiments can be run through a high-level Python API.

::

    import dallinger

    experiment = dallinger.experiments.Bartlett1932()
    data = experiment.run({
        mode=live,
        base_payment=1.00,
    })

All parameters in ``config.txt`` and ``.dallingerconfig`` can be specified
in the configuration dictionary passed to the ``run`` function. The return
value is an object that allows you to access all the Dallinger data tables
in a variety of useful formats. Here are all the tables:

::
    data.infos
    data.networks
    data.nodes
    data.notifications
    data.participants
    data.questions
    data.transformations
    data.transmissions
    data.vectors

For each of these tables, e.g. ``networks``, you can access it in a variety of
formats, including:

::

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


Note that, at the moment, only the Bartlett1932 demo can be run in this way.
