Monitoring a Live Experiment
============================

There are a number of ways that you can monitor a live experiment:

Command line tools
------------------

``dallinger summary --app {#id}``, where ``{#id}`` is the id (``w...``) of
the application.

This will print a summary showing the number of participants with each
status code, as well as the overall yield:

::

    status  | count
    ----------------
    1   | 26
    101 | 80
    103 | 43
    104 | 2

    Yield: 64.00%


The Dashboard
-------------

The Dallinger experiment server provides a dashboard view for experiment
administrators to monitor running experiments. The dasboard can be found at
``/dashboard``, and requires login credentials that are provided by the
commandline output when launching an experiment using ``dallinger debug``,
``dallinger sandbox``, or ``dallinger deploy``.

When running under ``dallinger debug`` a browser window should open with the
dashboard already logged in. The dashboard username and password can also be
found in the ``dashboard_user`` and ``dashboard_password`` configuration
parameters in the deployed ``config.txt`` configuration file. By default the
user is named ``admin`` and the password is generated randomly, but the user
name and password can be specified using configuration files.


Customizing the Dashboard
~~~~~~~~~~~~~~~~~~~~~~~~~

.. module:: dallinger.experiment_server.dashboard

You can add custom tabs to the Dallinger Dashboard by registering new
new `Flask routes <https://flask.palletsprojects.com/en/1.1.x/quickstart/#routing>`__ on the ``dashboard``
using the ``dashboard_tab`` decorator:

.. autofunction:: dashboard_tab

For example in your custom Experiment class could add the following code to add
a "My Experiment" tab to the dashboard:

.. code-block:: python

  from dallinger.experiment import Experiment
  from dallinger.experiment_server.dashboard import dashboard_tab

    class MyExperimentClass(Experiment

        @dashboard_tab("My Experiment")
        def my_experiment():
            return "Hello, World. This is some information about My Experiment"

This will regsiter the flask route on the dashboard as
``/dashboard/my_experiment`` under a tab named "My Experiment".

The dashboard also supports nested tab/menus using the
:attr:`~dallinger.experiment_server.dashboard.DashboardTab` object:

.. code-block:: python

  from dallinger.experiment_server.dashboard import dashboard_tabs, DashboardTab

  def child_tabs():
      return [DashboardTab('Child1', 'child1'), DashboardTab('Child2', 'child2')]

  complex_tab = DashboardTab('Title', 'route_name', child_tabs)
  dashboard_tabs.insert_tab(complex_tab)

The ``dashboard_tabs`` object supports the following methods for managing the
available tabs on your experiment's dashboard:

.. autoclass:: DashboardTabs

    .. automethod:: insert

    .. automethod:: insert_tab

    .. automethod:: insert_before_route

    .. automethod:: insert_tab_before_route

    .. automethod:: insert_after_route

    .. automethod:: insert_tab_after_route

    .. automethod:: remove


The :attr:`~dallinger.experiment_server.dashboard.DashboardTab` object used by
the various ``insert_tab*`` methods provide the following API:

.. autoclass:: DashboardTab

    .. automethod:: __init__


The dashboard monitoring view can be extended by adding panes to the sidebar or
extending the existing panes. This can be done customizing the
:attr:`~dallinger.experiment.Experiment.monitoring_panels` and/or
:attr:`~dallinger.experiment.Experiment.monitoring_statistics` methods of
your experiment class. Additionally, you can customize the display of the selected
nodes customizing the :attr:`~dallinger.experiment.Experiment.node_visualization_html`
method, or the :attr:`~dallinger.models.SharedMixin.visualization_html` property on your
model class. Finally, the layout of the visualization can be configured by customizing the
:attr:`~dallinger.experiment.Experiment.node_visualization_options` method to return
a dictionary of
`vis.js configuration options <https://visjs.github.io/vis-network/docs/network/#options>`__.

The dashboard database view can be customized by customizing the
:attr:`~dallinger.models.SharedMixin.json_data` method on your model classes to
add/modify data provided by each model to the dashboard views, or by modifying
the DataTables data returned by the
:attr:`~dallinger.experiment.Experiment.table_data` method in your
``Experiment`` class.

.. module:: dallinger.experiment
   :noindex:

.. autoclass:: Experiment
   :noindex:

    .. automethod:: monitoring_panels

    .. automethod:: monitoring_statistics

    .. automethod:: node_visualization_html

    .. automethod:: node_visualization_options

    .. automethod:: table_data

    .. automethod:: dashboard_database_actions
       :noindex:

You may also add new actions to the dashboard database view by adding additional
``title`` and ``name`` pairs to the
:func:`~dallinger.experiment.Experiment.dashboard_database_actions` output along
with corresponding methods that process submitted data. The
:func:`~dallinger.experiment.Experiment.dashboard_fail` method is an example of
such an action.


Papertrail
----------

You can use Papertrail to view and search the live logs of your
experiment. You can access the logs either through the Heroku
dashboard's Resources panel
(https://dashboard.heroku.com/apps/{#id}/resources), where {#id} is the
id of your experiment, or directly through Papertrail.com
(https://papertrailapp.com/systems/{#id}/events).

Setting up alerts
~~~~~~~~~~~~~~~~~

You can set up Papertrail to send error notifications to Slack or
another communications platform.

0.  Take a deep breath.
1.  Open the Papertrail logs.
2.  Search for the term ``error``.
3.  To the right of the search bar, you will see a button titled "+ Save
    Search". Click it. Name the search "Errors". Then click "Save &
    Setup an Alert", which is to the right of "Save Search".
4.  You will be directed to a page with a list of services that you can
    use to set up an alert.
5.  Click, e.g., Slack.
6.  Choose the desired frequency of alert. We recommend the minimum, 1
    minute.
7.  Under the heading "Slack details", open (*in a new tab or window*)
    the link `new Papertrail
    integration <link%20https://slack.com/services/new/papertrail>`__.
8.  This will bring you to a Slack page where you will choose a channel
    to post to. You may need to log in.
9.  Select the desired channel.
10. Click "Add Papertrail Integration".
11. You will be brought to a page with more information about the
    integration.
12. Scroll down to Step 3 to get the Webhook URL. It should look
    something like
    ``https://hooks.slack.com/services/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``.
13. Copy this link to your clipboard.
14. Change anything else you want and then scroll to the bottom and
    click "Save integration".
15. Go back to Papertrail page that you left in Step 7.
16. Paste the copied URL into the input text box labeled "Integration's
    Webhook URL" under the "Slack Details" heading.
17. Click "Create Alert" on the same page.
18. Victory.
