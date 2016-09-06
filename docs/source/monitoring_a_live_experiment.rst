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
